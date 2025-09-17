from __future__ import annotations

import logging
import subprocess
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from src.fiin_alerts.config import TIMEZONE
from src.fiin_alerts.logging import setup

LOG = logging.getLogger(__name__)
_TZ = ZoneInfo(TIMEZONE)


def _run_job(mode: str) -> None:
    cmd = [sys.executable, "-m", "src.fiin_alerts.jobs.generate_and_send_alerts", "--mode", mode]
    LOG.info("Launching %s job", mode)
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        LOG.error("Job %s exited with code %s", mode, result.returncode)


def create_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=_TZ)
    scheduler.add_job(
        _run_job,
        CronTrigger(hour="9-10,11", minute="*/15", day_of_week="mon-fri"),
        args=("INTRADAY",),
        name="intraday-morning",
    )
    scheduler.add_job(
        _run_job,
        CronTrigger(hour="13-14", minute="*/15", day_of_week="mon-fri"),
        args=("INTRADAY",),
        name="intraday-afternoon",
    )
    scheduler.add_job(
        _run_job,
        CronTrigger(hour=15, minute=2, day_of_week="mon-fri"),
        args=("EOD",),
        name="eod-close",
    )
    return scheduler


def main() -> None:
    setup()
    scheduler = create_scheduler()
    LOG.info("Scheduler started with jobs: %s", [job.name for job in scheduler.get_jobs()])
    scheduler.start()


if __name__ == "__main__":
    main()

