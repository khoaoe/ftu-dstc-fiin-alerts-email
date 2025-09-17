from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from typing import Any, Iterable, Tuple

from app.notify.alert_router_email import Alert as NotifyAlert

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


def _normalize_event(event: str) -> str:
    mapping = {"BUY": "BUY_NEW", "SELL": "SELL_TP"}
    upper = (event or "").upper()
    return mapping.get(upper, upper or "INFO")


def _resolve_tickers_input(raw: Iterable[str] | None, fallback: Iterable[str]) -> list[str]:
    if raw:
        resolved = [token.strip().upper() for token in raw if token and token.strip()]
        if resolved:
            return resolved
    return [ticker.upper() for ticker in fallback]


def _slot_bounds(ts: datetime | None, fallback: datetime, window_minutes: int = 15) -> tuple[datetime, datetime]:
    base = ts if ts is not None else fallback
    local = base if base.tzinfo else base.replace(tzinfo=_TZ)
    local = local.astimezone(_TZ)
    minute_slot = (local.minute // window_minutes) * window_minutes
    slot_start = local.replace(minute=minute_slot, second=0, microsecond=0)
    slot_end = slot_start + timedelta(minutes=window_minutes)
    return slot_start, slot_end


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


def produce_email_alerts(
    tickers: Iterable[str] | None = None,
    mode: str | None = None,
    as_of: datetime | None = None,
) -> list[NotifyAlert]:
    effective_mode = (mode or RUN_MODE).upper()
    fallback = DEFAULT_TICKERS or _DEFAULT_TICKERS
    resolved_tickers = _resolve_tickers_input(tickers, fallback)
    frame = pd.DataFrame()
    if effective_mode in {"INTRADAY", "BOTH"}:
        frame = _ingest_intraday(resolved_tickers)
    if frame.empty and effective_mode in {"EOD", "BOTH"}:
        frame = _ingest_from_parquet()
    alert_items = generate_alerts(frame)
    if not alert_items:
        return []
    reference_time = as_of.astimezone(_TZ) if as_of else datetime.now(_TZ)
    seen: set[tuple[str, str, datetime]] = set()
    results: list[NotifyAlert] = []
    for item in alert_items:
        raw_event = item.event_type or ""
        normalized_event = _normalize_event(raw_event)
        slot_start, slot_end = _slot_bounds(item.ts, reference_time)
        dedup_key = (item.ticker.upper(), normalized_event, slot_start)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        reason = item.explain or f"{normalized_event} signal"
        extras: dict[str, Any] = {
            "mode": effective_mode,
            "source": "v4_robust",
            "when": item.when,
            "raw_event": raw_event,
        }
        if item.price is not None:
            extras["price_hint"] = item.price
        results.append(
            NotifyAlert(
                ticker=item.ticker,
                event=normalized_event,
                slot_start=slot_start,
                slot_end=slot_end,
                price=item.price,
                reason=reason,
                extras=extras,
            )
        )
    return results


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
