
from __future__ import annotations

import argparse

from src.fiin_alerts.config import ALERT_FROM, ALERT_TO, SUBJECT_PREFIX
from src.fiin_alerts.logging import setup
from src.fiin_alerts.notify.composer import render_alert_email
from src.fiin_alerts.notify.gmail_client import send_email
from src.fiin_alerts.signals.v4_robust import AlertItem


def _parse_recipients(raw: str | None) -> list[str]:
    if not raw:
        return [addr for addr in ALERT_TO if addr]
    return [token.strip() for token in raw.split(',') if token.strip()]


def main() -> None:
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument('--to', help='Comma separated recipients override ALERT_TO')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    recipients = _parse_recipients(args.to)
    if not recipients:
        raise SystemExit('No recipients configured. Set ALERT_TO in .env or pass --to.')

    test_alerts = [AlertItem('TEST', 'INFO', 1234.0, 'now', 'Gmail API test alert')]
    html, text = render_alert_email(test_alerts)
    subject = SUBJECT_PREFIX + 'Test alert'

    if args.dry_run:
        print(f'DRY-RUN: would send to={recipients} subject={subject}')
        return

    msg_id = send_email(ALERT_FROM, recipients, subject, html, text)
    print(f'Gmail API send success message_id={msg_id}')


if __name__ == '__main__':
    main()
