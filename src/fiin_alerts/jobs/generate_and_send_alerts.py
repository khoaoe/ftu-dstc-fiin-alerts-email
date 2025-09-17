from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from typing import Any, Iterable

import pandas as pd
from zoneinfo import ZoneInfo

from app.notify.alert_router_email import Alert as NotifyAlert

from src.fiin_alerts.config import (
    DATA_PARQUET_PATH,
    DEFAULT_TICKERS,
    FQ_PASSWORD,
    FQ_USERNAME,
    HTTP_MAX_RETRY,
    INTRADAY_BY,
    INTRADAY_LOOKBACK_MIN,
    RUN_MODE,
    TIMEZONE,
)
from src.fiin_alerts.data.fiinquant_adapter import fetch_intraday
from src.fiin_alerts.data.parquet_adapter import load_recent_from_parquet
from src.fiin_alerts.feature.ta_intraday import enrich_intraday_features
from src.fiin_alerts.logging import setup
from src.fiin_alerts.signals.v4_robust import AlertItem, generate_alerts

LOG = logging.getLogger(__name__)
_TZ = ZoneInfo(TIMEZONE)
_DEFAULT_TICKERS = ["HPG", "SSI", "VCB", "VNM"]
_EVENT_LABELS = {
    "BUY_NEW": "Mua mới",
    "SELL_TP": "Bán chốt lời",
    "RISK": "Cảnh báo rủi ro",
}


def _parse_tickers(raw: str | None, fallback: Iterable[str]) -> list[str]:
    if raw:
        items = [token.strip().upper() for token in raw.split(",") if token.strip()]
        if items:
            return items
    return [ticker.upper() for ticker in fallback]


def _normalize_event(event: str) -> str:
    mapping = {"BUY": "BUY_NEW", "SELL": "SELL_TP"}
    upper = (event or "").upper()
    return mapping.get(upper, upper or "INFO")


def _event_label(event: str) -> str:
    return _EVENT_LABELS.get(event, event.replace("_", " ").title())


def _resolve_tickers_input(raw: Iterable[str] | None, fallback: Iterable[str]) -> list[str]:
    if raw:
        resolved = [token.strip().upper() for token in raw if token and token.strip()]
        if resolved:
            return resolved
    return [ticker.upper() for ticker in fallback]


def _slot_bounds(
    ts: datetime | None,
    fallback: datetime,
    window_minutes: int = 15,
) -> tuple[datetime, datetime]:
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


def _decorate_alert(
    item: AlertItem,
    mode: str,
    reference_time: datetime,
    seen: set[tuple[str, str, datetime]],
) -> NotifyAlert | None:
    raw_event = item.event_type or ""
    normalized_event = _normalize_event(raw_event)
    slot_start, slot_end = _slot_bounds(item.ts, reference_time)
    dedup_key = (item.ticker.upper(), normalized_event, slot_start)
    if dedup_key in seen:
        return None
    seen.add(dedup_key)
    label = _event_label(normalized_event)
    reason = item.explain or label
    extras: dict[str, Any] = {
        "mode": mode,
        "source": "v4_robust",
        "when": item.when,
        "raw_event": raw_event,
        "event_label": label,
    }
    if item.price is not None:
        extras["price_hint"] = item.price
    return NotifyAlert(
        ticker=item.ticker,
        event=normalized_event,
        slot_start=slot_start,
        slot_end=slot_end,
        price=item.price,
        reason=reason,
        extras=extras,
    )


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
        decorated = _decorate_alert(item, effective_mode, reference_time, seen)
        if decorated is not None:
            results.append(decorated)
    return results


def _build_log_summary(alerts: list[NotifyAlert]) -> str:
    lines: list[str] = []
    for alert in alerts[:10]:
        label = alert.extras.get("event_label") if alert.extras else None
        display_event = label or alert.event
        price = f"{alert.price:.2f}" if alert.price is not None else "-"
        lines.append(
            f"{alert.ticker} {display_event} price={price} window={alert.window_label()}"
        )
    extra = max(len(alerts) - len(lines), 0)
    if extra:
        lines.append(f"(+{extra} more)")
    return "\n".join(lines)


def _make_force_test_alert(reference_time: datetime, mode: str) -> NotifyAlert:
    slot_start, slot_end = _slot_bounds(reference_time, reference_time)
    label = "Kiểm thử"
    return NotifyAlert(
        ticker="TEST",
        event="INFO",
        slot_start=slot_start,
        slot_end=slot_end,
        price=1234.0,
        reason=label,
        extras={
            "mode": mode,
            "source": "force_test",
            "when": reference_time.strftime("%H:%M"),
            "raw_event": "INFO",
            "event_label": label,
        },
    )


def main() -> None:
    setup()

    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", help="Comma separated tickers override")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-test", action="store_true")
    parser.add_argument("--mode", choices=["INTRADAY", "EOD", "BOTH"])
    args = parser.parse_args()

    mode = (args.mode or RUN_MODE).upper()
    fallback_tickers = DEFAULT_TICKERS or _DEFAULT_TICKERS
    tickers = _parse_tickers(args.tickers, fallback_tickers)

    reference_time = datetime.now(_TZ)
    alerts = produce_email_alerts(
        tickers=tickers,
        mode=mode,
        as_of=reference_time,
    )

    if args.force_test:
        alerts = [_make_force_test_alert(reference_time, mode)]

    if not alerts:
        LOG.info("No alerts prepared for mode=%s", mode)
        return

    LOG.info("Prepared %s alerts for mode=%s", len(alerts), mode)
    LOG.info("Summary:\n%s", _build_log_summary(alerts))

    if args.dry_run:
        LOG.info("Dry-run: alerts retained in memory, scheduler/router handles dispatch.")
        return

    LOG.info("Alerts ready. Use the scheduler pipeline to dispatch via SMTP.")


if __name__ == "__main__":
    main()
