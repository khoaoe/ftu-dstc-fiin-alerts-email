from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import smtplib
import socket
import sqlite3
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from zoneinfo import ZoneInfo

load_dotenv()

LOG = logging.getLogger(__name__)
_TRANSIENT_SMTP_CODES = {421, 450, 451, 452}
_DEFAULT_TIMEZONE = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")
_TZ = ZoneInfo(_DEFAULT_TIMEZONE)


def _ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_TZ)
    return value.astimezone(_TZ)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Alert:
    ticker: str
    event: str
    slot_start: datetime
    slot_end: datetime
    price: float | None
    reason: str
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.upper())
        object.__setattr__(self, "event", self.event.upper())
        object.__setattr__(self, "slot_start", _ensure_timezone(self.slot_start))
        object.__setattr__(self, "slot_end", _ensure_timezone(self.slot_end))

    def window_label(self) -> str:
        return f"{self.slot_start.isoformat()}|{self.slot_end.isoformat()}"


class Outbox:
    """SQLite-backed deduplication and logging storage."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        db_path = path or os.getenv("ALERT_DB_PATH", "alerts.db")
        self.path = Path(db_path)
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30, check_same_thread=False)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts_sent(
                    hash TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    event TEXT NOT NULL,
                    window TEXT NOT NULL,
                    first_sent_ts TEXT NOT NULL,
                    channels TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts_outbox(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    event TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resp_code TEXT,
                    resp_body TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def already_sent(self, alert_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM alerts_sent WHERE hash = ?",
                (alert_hash,),
            ).fetchone()
            return row is not None

    def mark_sent(self, alert_hash: str, alert: Alert, channel: str = "email") -> None:
        window = alert.window_label()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alerts_sent(hash, ticker, event, window, first_sent_ts, channels)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(hash) DO UPDATE SET
                    channels = CASE
                        WHEN alerts_sent.channels LIKE '%' || excluded.channels || '%' THEN alerts_sent.channels
                        WHEN alerts_sent.channels = '' THEN excluded.channels
                        ELSE alerts_sent.channels || ',' || excluded.channels
                    END
                """,
                (
                    alert_hash,
                    alert.ticker,
                    alert.event,
                    window,
                    _now_utc_iso(),
                    channel,
                ),
            )
            conn.commit()

    def log_attempt(
        self,
        alert_hash: str,
        alert: Alert,
        status: str,
        channel: str = "email",
        resp_code: str | None = None,
        resp_body: str | None = None,
        retry_count: int = 0,
    ) -> None:
        body = (resp_body or "")
        if len(body) > 768:
            body = body[:768]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alerts_outbox(ts, channel, ticker, event, hash, status, resp_code, resp_body, retry_count)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now_utc_iso(),
                    channel,
                    alert.ticker,
                    alert.event,
                    alert_hash,
                    status,
                    resp_code,
                    body,
                    retry_count,
                ),
            )
            conn.commit()


class EmailChannel:
    """SMTP email sender with retry/backoff and HTML composition."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        security: str | None = None,
        user: str | None = None,
        password: str | None = None,
        recipients: Iterable[str] | None = None,
        sender: str | None = None,
        subject_prefix: str | None = None,
        env_name: str | None = None,
        max_retry: int | None = None,
        base_delay: float = 1.0,
    ) -> None:
        self.host = host or os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.port = int(port or os.getenv("SMTP_PORT", "465"))
        self.security = (security or os.getenv("SMTP_SECURITY", "SSL")).upper()
        self.user = user or os.getenv("SMTP_USER")
        self.password = password or os.getenv("SMTP_PASS")
        if recipients is not None:
            provided = [addr.strip() for addr in recipients if addr.strip()]
        else:
            raw_recipients = os.getenv("MAIL_TO", "")
            provided = [addr.strip() for addr in raw_recipients.split(",") if addr.strip()]
        self.recipients = provided
        self.sender = sender or os.getenv("SMTP_SENDER") or self.user
        self.subject_prefix = subject_prefix or os.getenv("SUBJECT_PREFIX", "[FTU-DSTC Alerts] ")
        self.env_name = env_name or os.getenv("ENV_NAME", "prod")
        self.max_retry = max(int(max_retry or 3), 1)
        self.base_delay = max(base_delay, 0.2)
        self.timeout = float(os.getenv("SMTP_TIMEOUT", "30"))
        if not self.sender:
            raise ValueError("SMTP sender email is required")
        if not self.recipients:
            raise ValueError("At least one MAIL_TO recipient is required")
        if not self.user or not self.password:
            raise ValueError("SMTP_USER and SMTP_PASS must be configured")

    def _build_message(self, alert: Alert) -> EmailMessage:
        window = alert.window_label()
        extras_json = json.dumps(alert.extras, ensure_ascii=True, separators=(",", ":")) if alert.extras else "{}"
        price_text = f"{alert.price:.2f}" if alert.price is not None else "-"
        subject = f"{self.subject_prefix}{alert.ticker} {alert.event} [{self.env_name}]"
        html = f"""
        <html>
          <body>
            <h3>Alert: {alert.ticker} - {alert.event}</h3>
            <p><strong>Window:</strong> {window}</p>
            <p><strong>Price:</strong> {price_text}</p>
            <p><strong>Reason:</strong> {alert.reason}</p>
            <pre style="background-color:#f4f4f4;padding:8px;border-radius:4px;">{extras_json}</pre>
          </body>
        </html>
        """
        plain = (
            f"Alert {alert.ticker} {alert.event}\n"
            f"Window: {window}\n"
            f"Price: {price_text}\n"
            f"Reason: {alert.reason}\n"
            f"Extras: {extras_json}"
        )
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(plain)
        message.add_alternative(html, subtype="html")
        return message

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self.security == "SSL":
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
            server.ehlo()
        elif self.security == "TLS":
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
        else:
            raise ValueError("SMTP_SECURITY must be SSL or TLS")
        server.login(self.user, self.password)
        return server

    def _should_retry(self, error: Exception) -> bool:
        code = getattr(error, "smtp_code", None)
        if code in _TRANSIENT_SMTP_CODES:
            return True
        if isinstance(
            error,
            (
                smtplib.SMTPServerDisconnected,
                smtplib.SMTPConnectError,
                smtplib.SMTPDataError,
                smtplib.SMTPHeloError,
                socket.timeout,
                TimeoutError,
                ConnectionError,
            ),
        ):
            return True
        return False

    def send(self, alert: Alert, alert_hash: str, outbox: Outbox) -> bool:
        message = self._build_message(alert)
        delay = self.base_delay
        for attempt in range(self.max_retry):
            try:
                with self._connect() as server:
                    refused = server.send_message(message)
                status = "SENT" if not refused else "PARTIAL"
                outbox.log_attempt(
                    alert_hash=alert_hash,
                    alert=alert,
                    status=status,
                    resp_code="250",
                    resp_body=json.dumps(refused, default=str) if refused else "OK",
                    retry_count=attempt,
                )
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
                LOG.info(
                    "Email sent ticker=%s event=%s hash=%s recipients=%s",
                    alert.ticker,
                    alert.event,
                    alert_hash,
                    len(self.recipients),
                )
                return True
            except Exception as exc:  # broad to ensure logging
                code = getattr(exc, "smtp_code", None)
                err_text = getattr(exc, "smtp_error", b"")
                if isinstance(err_text, bytes):
                    try:
                        err_text = err_text.decode("utf-8", "ignore")
                    except Exception:
                        err_text = repr(err_text)
                resp_body = str(err_text or exc)
                outbox.log_attempt(
                    alert_hash=alert_hash,
                    alert=alert,
                    status="ERROR",
                    resp_code=str(code) if code is not None else None,
                    resp_body=resp_body,
                    retry_count=attempt,
                )
                should_retry = self._should_retry(exc)
                if not should_retry or attempt == self.max_retry - 1:
                    LOG.error(
                        "Email send failed ticker=%s event=%s attempt=%s/%s retry=%s",
                        alert.ticker,
                        alert.event,
                        attempt + 1,
                        self.max_retry,
                        should_retry,
                    )
                    return False
                sleep_for = delay + random.uniform(0.0, 0.5)
                LOG.warning(
                    "Transient SMTP error code=%s attempt=%s/%s sleeping %.2fs",
                    getattr(exc, "smtp_code", "?"),
                    attempt + 1,
                    self.max_retry,
                    sleep_for,
                )
                time.sleep(sleep_for)
                delay *= 2
        return False


class AlertRouterEmail:
    def __init__(self, outbox: Outbox | None = None, channel: EmailChannel | None = None) -> None:
        self.outbox = outbox or Outbox()
        self.channel = channel or EmailChannel()

    @staticmethod
    def compute_hash(alert: Alert) -> str:
        slot_start = alert.slot_start.astimezone(timezone.utc).isoformat()
        slot_end = alert.slot_end.astimezone(timezone.utc).isoformat()
        content = f"{alert.ticker}|{alert.event}|{slot_start}|{slot_end}|v1"
        return hashlib.sha1(content.encode("utf-8")).hexdigest()

    def send_alert(self, alert: Alert) -> bool:
        alert_hash = self.compute_hash(alert)
        if self.outbox.already_sent(alert_hash):
            LOG.info("Skip duplicate alert ticker=%s event=%s hash=%s", alert.ticker, alert.event, alert_hash)
            return False
        try:
            sent = self.channel.send(alert, alert_hash, self.outbox)
        except ValueError as exc:
            LOG.error("Misconfigured email channel: %s", exc)
            return False
        if sent:
            self.outbox.mark_sent(alert_hash, alert)
            return True
        return False


def _demo() -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    now = datetime.now(_TZ)
    start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    alert = Alert(
        ticker="HPG",
        event="BUY_NEW",
        slot_start=start,
        slot_end=now,
        price=32500.0,
        reason="RSI14=62, MACD cross up, Close>SMA20, vol_spike=+55%",
        extras={"env": os.getenv("ENV_NAME", "prod")},
    )
    router = AlertRouterEmail()
    result = router.send_alert(alert)
    print(f"SENT: {result}")


if __name__ == "__main__":
    _demo()
