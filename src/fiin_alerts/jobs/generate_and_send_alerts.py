from __future__ import annotations

import argparse
import logging
from datetime import datetime
from typing import Iterable, Tuple

import pandas as pd
from zoneinfo import ZoneInfo

from src.fiin_alerts.config import (
    ALERT_FROM,
    ALERT_TO,
    DATA_PARQUET_PATH,
    DEFAULT_TICKERS,
    FQ_PASSWORD,
    FQ_USERNAME,
    GMAIL_MAX_RETRY,
    HTTP_MAX_RETRY,
    INTRADAY_BY,
    INTRADAY_LOOKBACK_MIN,
    RUN_MODE,
    SUBJECT_PREFIX,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_IDS,
    TIMEZONE,
)
from src.fiin_alerts.data.fiinquant_adapter import fetch_intraday
from src.fiin_alerts.data.parquet_adapter import load_recent_from_parquet
from src.fiin_alerts.feature.ta_intraday import enrich_intraday_features
from src.fiin_alerts.logging import setup
from src.fiin_alerts.notify.composer import render_alert_email
from src.fiin_alerts.notify.gmail_client import send_email
from src.fiin_alerts.notify.telegram_client import send_telegram
from src.fiin_alerts.signals.v4_robust import AlertItem, generate_alerts
from src.fiin_alerts.state.store import already_sent, mark_sent

LOG = logging.getLogger(__name__)
_TZ = ZoneInfo(TIMEZONE)
_DEFAULT_TICKERS = ["HPG", "SSI", "VCB", "VNM"]


def _parse_tickers(raw: str | None, fallback: Iterable[str]) -> list[str]:
    if raw:
        items = [token.strip().upper() for token in raw.split(",") if token.strip()]
        if items:
            return items
    return [ticker.upper() for ticker in fallback]


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_summaries(alerts: list[AlertItem]) -> Tuple[str, str]:
    lines: list[str] = []
    for alert in alerts[:10]:
        price = f"{alert.price:.2f}" if alert.price is not None else "-"
        when = alert.when or ""
        lines.append(f"{alert.ticker} {alert.event_type} {price} {when}")
    extra = max(len(alerts) - 10, 0)
    if extra:
        lines.append(f"(+{extra} more)")
    plain = "\n".join(lines)
    html = "<br>".join(_escape_html(line) for line in lines)
    return plain, html


def _floor_15(ts: datetime | None) -> str:
    if ts is None:
        return ""
    local = ts if ts.tzinfo else ts.replace(tzinfo=_TZ)
    local = local.astimezone(_TZ)
    minute_slot = (local.minute // 15) * 15
    floored = local.replace(minute=minute_slot, second=0, microsecond=0)
    return floored.strftime("%Y-%m-%d %H:%M")


def _ingest_intraday(tickers: list[str]) -> pd.DataFrame:
    if not (FQ_USERNAME and FQ_PASSWORD):
        return pd.DataFrame()
    df = fetch_intraday(
        username=FQ_USERNAME,
        password=FQ_PASSWORD,
        tickers=tickers,
        minutes=INTRADAY_LOOKBACK_MIN,
        by=INTRADAY_BY,
        max_retry=HTTP_MAX_RETRY,
    )
    if df.empty:
        return pd.DataFrame()
    return enrich_intraday_features(df)


def _ingest_from_parquet() -> pd.DataFrame:
    if not DATA_PARQUET_PATH:
        return pd.DataFrame()
    df = load_recent_from_parquet(DATA_PARQUET_PATH)
    if df.empty:
        return df
    return enrich_intraday_features(df)


def main() -> None:
    setup()

    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", help="Comma separated tickers override")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--to", help="Comma separated recipients to override .env")
    parser.add_argument("--force-test", action="store_true")
    parser.add_argument("--mode", choices=["INTRADAY", "EOD", "BOTH"])
    args = parser.parse_args()

    mode = (args.mode or RUN_MODE).upper()
    fallback_tickers = DEFAULT_TICKERS or _DEFAULT_TICKERS
    tickers = _parse_tickers(args.tickers, fallback_tickers)

    frame = pd.DataFrame()
    if mode in {"INTRADAY", "BOTH"}:
        frame = _ingest_intraday(tickers)
    if frame.empty:
        frame = _ingest_from_parquet()

    if frame.empty:
        LOG.info("No data available for alerts generation")

    alerts = generate_alerts(frame)

    if args.force_test:
        now_local = datetime.now(_TZ)
        alerts = [
            AlertItem(
                ticker="TEST",
                event_type="INFO",
                price=1234.0,
                when=now_local.strftime("%H:%M"),
                explain="Force test alert",
                ts=now_local,
            )
        ]

    if not alerts:
        LOG.info("No alerts to send")
        return

    deduped: list[AlertItem] = []
    keys: list[str] = []
    for alert in alerts:
        slot = _floor_15(alert.ts) or alert.when
        key = f"{alert.ticker}:{alert.event_type}:{slot}"
        if already_sent(key):
            LOG.debug("Skip duplicate alert key=%s", key)
            continue
        deduped.append(alert)
        keys.append(key)

    if not deduped:
        LOG.info("All alerts already sent for this slot")
        return

    recipients_raw = args.to if args.to else ",".join(ALERT_TO)
    recipients = [addr.strip() for addr in recipients_raw.split(",") if addr.strip()]
    if not recipients:
        LOG.error("No recipients configured")
        return

    html, text = render_alert_email(deduped)
    mode_tag = f"[{mode}] " if mode not in {"INTRADAY", "BOTH"} else f"[{mode}/{INTRADAY_BY}] "
    subject = f"{SUBJECT_PREFIX}{mode_tag}{len(deduped)} alerts"

    summary_plain, summary_html = _build_summaries(deduped)
    LOG.info("Prepared %s alerts", len(deduped))
    LOG.info("Summary:\n%s", summary_plain)

    if args.dry_run:
        LOG.info("Dry-run enabled. Skipping email/telegram send")
        return

    try:
        message_id = send_email(
            ALERT_FROM,
            recipients,
            subject,
            html,
            text,
            max_retry=GMAIL_MAX_RETRY,
        )
    except Exception as exc:
        LOG.error("Email send failed: %s", exc.__class__.__name__)
        return

    mark_sent(keys)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS:
        telegram_ids = send_telegram(
            token=TELEGRAM_BOT_TOKEN,
            chat_ids=TELEGRAM_CHAT_IDS,
            text=summary_html,
            max_retry=HTTP_MAX_RETRY,
        )
        if telegram_ids:
            LOG.info("Telegram notifications sent count=%s", len(telegram_ids))

    LOG.info("Email sent message_id=%s", message_id)


if __name__ == "__main__":
    main()
