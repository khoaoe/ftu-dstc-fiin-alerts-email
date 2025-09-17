from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

from app.notify.alert_router_email import Alert, AlertRouterEmail, EmailChannel
from src.fiin_alerts.config import TIMEZONE
from src.fiin_alerts.logging import setup


def _parse_recipients(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    recipients = [item.strip() for item in raw.split(",") if item.strip()]
    return recipients or None


def main() -> None:
    setup()
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", help="Comma separated recipients override MAIL_TO")
    args = parser.parse_args()

    recipients = _parse_recipients(args.to)
    channel = EmailChannel(recipients=recipients) if recipients else None
    router = AlertRouterEmail(channel=channel)

    now = datetime.now(ZoneInfo(TIMEZONE))
    slot_start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    slot_end = slot_start + timedelta(minutes=15)
    alert = Alert(
        ticker="TEST",
        event="INFO",
        slot_start=slot_start,
        slot_end=slot_end,
        price=1234.0,
        reason="SMTP test alert",
        extras={
            "mode": "TEST",
            "source": "send_test_email",
            "event_label": "Kiểm thử",
        },
    )
    sent = router.send_alert(alert)
    status = "OK" if sent else "SKIPPED"
    print(f"SMTP test result: {status}")


if __name__ == "__main__":
    main()
