from __future__ import annotations

import logging
import os
from typing import Iterable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

from src.fiin_alerts.jobs.generate_and_send_alerts import run_once
from src.fiin_alerts.logging import setup as setup_logging

load_dotenv()

LOG = logging.getLogger(__name__)
_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh"))


def run_signals_and_notify(
    mode: str = "BOTH",
    tickers: Iterable[str] | None = None,
    recipients: Iterable[str] | None = None,
    dry_run: bool = False,
) -> int:
    """Trigger alert generation and send via Gmail API."""
    effective_mode = (mode or "BOTH").upper()
    sent = run_once(
        mode=effective_mode,
        tickers=tickers,
        recipients=recipients,
        dry_run=dry_run,
    )
    LOG.info("Notify run mode=%s sent=%s", effective_mode, sent)
    return sent


def _start_scheduler() -> None:
    setup_logging()
    scheduler = BlockingScheduler(timezone=_TZ)
    intraday_schedules = [
        ("notify_am", {"hour": "9-10", "minute": "*/15"}),
        ("notify_late_morning", {"hour": 11, "minute": "0,15,30"}),
        ("notify_pm", {"hour": 13, "minute": "*/15"}),
        ("notify_late_pm", {"hour": 14, "minute": "0,15,30"}),
    ]
    for job_id, cron_kwargs in intraday_schedules:
        scheduler.add_job(
            run_signals_and_notify,
            CronTrigger(timezone=_TZ, **cron_kwargs),
            id=job_id,
            kwargs={"mode": "INTRADAY"},
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
        )
    scheduler.add_job(
        run_signals_and_notify,
        CronTrigger(hour=15, minute=0, timezone=_TZ),
        id="notify_eod",
        kwargs={"mode": "EOD"},
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
