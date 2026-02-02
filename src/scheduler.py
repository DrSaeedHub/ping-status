"""Job scheduler: run ping jobs every N minutes and send report to admin."""
import threading
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.jobs_store import load_jobs
from src.ping_worker import PingResult, format_report, run_ping

# Callback: (admin_user_id: int, text: str) -> None
SendMessageFunc = Callable[[int, str], None]


def _run_job(job: dict, send_message: SendMessageFunc, admin_user_id: int) -> None:
    """Run one ping job and send report to admin."""
    name = job.get("name", "?")
    target = job.get("target", "")
    count = int(job.get("count", 10))
    interval_sec = float(job.get("interval_sec", 0.2))
    if not target:
        send_message(admin_user_id, f"Job '{name}': missing target.")
        return
    result: PingResult = run_ping(target, count, interval_sec)
    text = format_report(name, result)
    send_message(admin_user_id, text)


def start_scheduler(send_message: SendMessageFunc, admin_user_id: int) -> BackgroundScheduler:
    """
    Start background scheduler that runs jobs from jobs.json every N minutes.
    Returns the scheduler instance (call .shutdown() to stop).
    """
    scheduler = BackgroundScheduler()
    jobs = load_jobs()

    for job in jobs:
        name = job.get("name", "?")
        schedule_minutes = int(job.get("schedule_minutes", 5))
        if schedule_minutes < 1:
            schedule_minutes = 1
        job_id = f"ping_{name}"
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
        scheduler.add_job(
            _run_job,
            trigger=IntervalTrigger(minutes=schedule_minutes),
            id=job_id,
            args=[job, send_message, admin_user_id],
            replace_existing=True,
        )

    scheduler.start()
    return scheduler


def reload_scheduler(
    scheduler: BackgroundScheduler,
    send_message: SendMessageFunc,
    admin_user_id: int,
) -> None:
    """Reload jobs from disk and reschedule (add/remove/update)."""
    scheduler.remove_all_jobs()
    jobs = load_jobs()
    for job in jobs:
        name = job.get("name", "?")
        schedule_minutes = max(1, int(job.get("schedule_minutes", 5)))
        job_id = f"ping_{name}"
        scheduler.add_job(
            _run_job,
            trigger=IntervalTrigger(minutes=schedule_minutes),
            id=job_id,
            args=[job, send_message, admin_user_id],
            replace_existing=True,
        )
