from __future__ import annotations
import argparse
import logging

from app.notify.alert_router_email import Alert as NotifyAlert

from src.fiin_alerts.config import (
    ALERT_TO,
    ALERT_FROM,
    SUBJECT_PREFIX,
    DATA_PARQUET_PATH,
    FQ_USERNAME,
    FQ_PASSWORD,
)
from src.fiin_alerts.logging import setup
from src.fiin_alerts.data.parquet_adapter import load_recent_from_parquet
from src.fiin_alerts.data.fiinquant_adapter import fetch_intraday
from src.fiin_alerts.signals.v4_robust import generate_alerts
from src.fiin_alerts.notify.composer import render_alert_email
from src.fiin_alerts.notify.gmail_client import send_email
from src.fiin_alerts.state.store import already_sent, mark_sent

LOG = logging.getLogger(__name__)

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="HPG,SSI,VCB,VNM")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--to", help="comma-separated recipients (override .env)")
    ap.add_argument("--force-test", action="store_true")
    args = ap.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    # Try realtime via FiinQuantX first, fallback to parquet
    df = fetch_intraday(FQ_USERNAME, FQ_PASSWORD, tickers) if FQ_USERNAME and FQ_PASSWORD else None
    if df is None or df.empty:
        df = load_recent_from_parquet(DATA_PARQUET_PATH) if DATA_PARQUET_PATH else None

    if df is None or df.empty:
        LOG.info("Source empty: check FiinQuant or PARQUET path/columns")
    else:
        LOG.info("DF shape=%s, cols=%s, head=\n%s", df.shape, list(df.columns)[:12], df.head(3))

    alerts = generate_alerts(df) if df is not None else []
    if args.force_test:
        from src.fiin_alerts.signals.v4_robust import AlertItem

        alerts = [AlertItem("TEST", "BUY", 12345.0, "now", "forced")]

    if not alerts:
        LOG.info("No alerts.")
        return

    # de-dupe by (ticker,event_type)
    new_alerts = []
    keys: list[str] = []
    for a in alerts:
        k = f"{a.ticker}:{a.event_type}"
        if not already_sent(k):
            new_alerts.append(a)
            keys.append(k)

    if not new_alerts:
        LOG.info("All alerts were duplicates. Skipping send.")
        return

    tos_raw = args.to if args.to else ",".join(ALERT_TO)
    tos = [e.strip() for e in tos_raw.split(",") if e.strip()]
    if not tos:
        LOG.error("No recipients. Set ALERT_TO in .env or pass --to")
        return

    html, text = render_alert_email(new_alerts)
    subj = SUBJECT_PREFIX + f"{len(new_alerts)} alerts"
    if args.dry_run:
        LOG.info("DRY RUN — would send to=%s subj=%s", tos, subj)
        return

    msg_id = send_email(ALERT_FROM, tos, subj, html, text)
    mark_sent(keys)
    LOG.info("Sent alerts msg_id=%s", msg_id)

if __name__ == "__main__":
    main()
