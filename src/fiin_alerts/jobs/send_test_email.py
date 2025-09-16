from __future__ import annotations
import argparse
from src.fiin_alerts.notify.gmail_client import send_email
from src.fiin_alerts.notify.composer import render_alert_email
from src.fiin_alerts.config import ALERT_FROM, SUBJECT_PREFIX
from src.fiin_alerts.logging import setup

def main():
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="comma-separated recipients")
    args = ap.parse_args()
    to = [e.strip() for e in args.to.split(",") if e.strip()]
    alerts = [{"ticker":"VNM","event_type":"TEST","price":72000,"when":"now","explain":"hello"}]
    html, text = render_alert_email(alerts)
    send_email(ALERT_FROM, to, SUBJECT_PREFIX + "Test", html, text)

if __name__ == "__main__":
    main()
