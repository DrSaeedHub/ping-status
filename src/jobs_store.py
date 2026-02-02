"""Thread-safe read/write of jobs.json."""
import json
import threading
from pathlib import Path
from typing import Any

from src.config import get_jobs_path
from src.error_reporting import send_error

_LOCK = threading.Lock()

JOBS_KEY = "jobs"


def _ensure_file(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(json.dumps({JOBS_KEY: []}, indent=2), encoding="utf-8")
    except Exception as e:
        send_error(e, "jobs_store: _ensure_file")


def load_jobs() -> list[dict[str, Any]]:
    """Load jobs list from disk. Returns list of job dicts."""
    path = get_jobs_path()
    with _LOCK:
        try:
            _ensure_file(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get(JOBS_KEY, [])
        except Exception as e:
            send_error(e, "jobs_store: load_jobs")
            return []


def save_jobs(jobs: list[dict[str, Any]]) -> None:
    """Write jobs list to disk."""
    path = get_jobs_path()
    with _LOCK:
        try:
            _ensure_file(path)
            path.write_text(json.dumps({JOBS_KEY: jobs}, indent=2), encoding="utf-8")
        except Exception as e:
            send_error(e, "jobs_store: save_jobs")
            raise


def get_job_by_name(name: str) -> dict[str, Any] | None:
    """Return first job with given name or None."""
    for j in load_jobs():
        if j.get("name") == name:
            return j
    return None


def add_job(job: dict[str, Any]) -> bool:
    """Add job if name is unique. Returns True if added."""
    jobs = load_jobs()
    names = {j.get("name") for j in jobs}
    if job.get("name") in names:
        return False
    jobs.append(job)
    save_jobs(jobs)
    return True


def update_job(name: str, updates: dict[str, Any]) -> bool:
    """Update first job with given name. Returns True if found."""
    jobs = load_jobs()
    for i, j in enumerate(jobs):
        if j.get("name") == name:
            jobs[i] = {**j, **updates}
            save_jobs(jobs)
            return True
    return False


def delete_job(name: str) -> bool:
    """Remove first job with given name. Returns True if removed."""
    jobs = load_jobs()
    new_jobs = [j for j in jobs if j.get("name") != name]
    if len(new_jobs) == len(jobs):
        return False
    save_jobs(new_jobs)
    return True
