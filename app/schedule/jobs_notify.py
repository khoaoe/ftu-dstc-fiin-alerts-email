from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Iterable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

from app.notify.alert_router_email import AlertRouterEmail
from src.fiin_alerts.jobs.generate_and_send_alerts import produce_email_alerts
from src.fiin_alerts.logging import setup as setup_logging

load_dotenv()

LOG = logging.getLogger(__name__)
_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh"))


def run_signals_and_notify(
    mode: str = "BOTH",
    tickers: Iterable[str] | None = None,
    as_of: datetime | None = None,
    router: AlertRouterEmail | None = None,
) -> int:
    """Fetch signals, build alerts, and send them via email."""
    effective_mode = (mode or "BOTH").upper()
    reference_time = as_of.astimezone(_TZ) if as_of else datetime.now(_TZ)
    alerts = produce_email_alerts(tickers=tickers, mode=effective_mode, as_of=reference_time)
    if not alerts:
        LOG.info("Notify run mode=%s nothing-to-send", effective_mode)
        return 0
    active_router = router or AlertRouterEmail()
    sent = 0
    for alert in alerts:
        if active_router.send_alert(alert):
            sent += 1
    LOG.info(
        "Notify run mode=%s total=%s sent=%s duplicates=%s",
        effective_mode,
        len(alerts),
        sent,
        len(alerts) - sent,
    )
    return sent


def _start_scheduler() -> None:
    setup_logging()
    scheduler = BlockingScheduler(timezone=_TZ)
    router = AlertRouterEmail()
    scheduler.add_job(
        run_signals_and_notify,
        CronTrigger.from_crontab("*/15 * * * *", timezone=_TZ),
        id="notify_15m",
        kwargs={"mode": "INTRADAY", "router": router},
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        run_signals_and_notify,
        CronTrigger(hour=15, minute=0, timezone=_TZ),
        id="notify_eod",
        kwargs={"mode": "EOD", "router": router},
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    LOG.info("Notify scheduler started timezone=%s", _TZ)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        LOG.info("Scheduler stopping")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    _start_scheduler()
