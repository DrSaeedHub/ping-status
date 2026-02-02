"""Job scheduler: check every 10s and run jobs when next_run (last_run + schedule) has passed."""
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.error_reporting import send_error
from src.jobs_store import load_jobs, update_job
from src.ping_worker import PingResult, format_report, run_ping

# Callback: (admin_user_id: int, text: str) -> None
SendMessageFunc = Callable[[int, str], None]

_TICK_JOB_ID = "ping_tick"
_CHECK_INTERVAL_SEC = 10


def _parse_last_run(iso_str: str | None) -> datetime | None:
    """Parse last_run_at ISO string to timezone-aware datetime. Returns None if missing/invalid."""
    if not iso_str:
        return None
    try:
        s = (iso_str or "").strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError) as e:
        send_error(e, "scheduler: _parse_last_run")
        return None


def _run_job(job: dict, send_message: SendMessageFunc, admin_user_id: int) -> None:
    """Run one ping job and send report to admin."""
    try:
        name = job.get("name", "?")
        target = job.get("target", "")
        count = int(job.get("count", 10))
        interval_sec = float(job.get("interval_sec", 0.2))
        if not target:
            send_message(admin_user_id, f"⚠️ <b>Job skipped:</b> <code>{escape(str(name), quote=False)}</code>\nMissing target.")
            return
        result: PingResult = run_ping(target, count, interval_sec)
        text = format_report(name, result)
        send_message(admin_user_id, text)
        update_job(name, {"last_run_at": datetime.now(timezone.utc).isoformat()})
    except Exception as e:
        send_error(e, f"scheduler: _run_job name={job.get('name', '?')}")


def _tick(send_message: SendMessageFunc, admin_user_id: int) -> None:
    """Run every 10s: load jobs, run any whose next_run (last_run + schedule) <= now."""
    try:
        now = datetime.now(timezone.utc)
        jobs = load_jobs()
        for job in jobs:
            name = job.get("name", "?")
            schedule_minutes = max(1, int(job.get("schedule_minutes", 5)))
            last_run = _parse_last_run(job.get("last_run_at"))
            if last_run is None:
                next_run = now  # run immediately if never run
            else:
                next_run = last_run + timedelta(minutes=schedule_minutes)
            if now >= next_run:
                _run_job(job, send_message, admin_user_id)
    except Exception as e:
        send_error(e, "scheduler: _tick")


def start_scheduler(send_message: SendMessageFunc, admin_user_id: int) -> BackgroundScheduler:
    """
    Start background scheduler: one job runs every 10s and executes any job whose
    next run time (last_run_at + schedule_minutes) has passed.
    Returns the scheduler instance (call .shutdown() to stop).
    """
    try:
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _tick,
            trigger=IntervalTrigger(seconds=_CHECK_INTERVAL_SEC),
            id=_TICK_JOB_ID,
            args=[send_message, admin_user_id],
            replace_existing=True,
        )
        scheduler.start()
        return scheduler
    except Exception as e:
        send_error(e, "scheduler: start_scheduler")
        raise


def reload_scheduler(
    scheduler: BackgroundScheduler,
    send_message: SendMessageFunc,
    admin_user_id: int,
) -> None:
    """No-op: tick loads jobs from disk every 10s, so no reload needed."""
    pass


def get_next_run_times(_scheduler: object = None) -> dict[str, datetime]:
    """Return {job_name: next_run_time} from jobs (last_run_at + schedule_minutes). Timezone-aware."""
    try:
        out: dict[str, datetime] = {}
        now = datetime.now(timezone.utc)
        for job in load_jobs():
            name = job.get("name", "?")
            schedule_minutes = max(1, int(job.get("schedule_minutes", 5)))
            last_run = _parse_last_run(job.get("last_run_at"))
            if last_run is None:
                next_run = now
            else:
                next_run = last_run + timedelta(minutes=schedule_minutes)
            out[name] = next_run
        return out
    except Exception as e:
        send_error(e, "scheduler: get_next_run_times")
        return {}


def run_job_now(
    scheduler: BackgroundScheduler | None,
    job_name: str,
    send_message: SendMessageFunc,
    admin_user_id: int,
    *,
    skip_progress: bool = False,
) -> None:
    """Run one job immediately: optionally send progress message, then run ping and send report."""
    try:
        from src.jobs_store import get_job_by_name

        if not scheduler or not send_message:
            return
        job = get_job_by_name(job_name)
        if not job:
            send_message(admin_user_id, f"❌ <b>Job not found:</b> <code>{escape(str(job_name), quote=False)}</code>")
            return
        if not skip_progress:
            send_message(admin_user_id, f"▶️ <b>Running now:</b> <code>{escape(str(job_name), quote=False)}</code>")
        _run_job(job, send_message, admin_user_id)
    except Exception as e:
        send_error(e, f"scheduler: run_job_now name={job_name}")
