from __future__ import annotations
import argparse
import logging

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
