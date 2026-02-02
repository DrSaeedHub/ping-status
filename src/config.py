"""Load and validate .env; expose BOT_TOKEN, ADMIN_USER_ID, paths."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Resolve project root (directory containing src/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
_JOBS_PATH = _PROJECT_ROOT / "jobs.json"

load_dotenv(_ENV_PATH)


def _get(key: str, default: str | None = None) -> str:
    val = os.environ.get(key, default)
    return val.strip() if val else (default or "")


def _get_int(key: str, default: int) -> int:
    try:
        return int(_get(key) or default)
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    try:
        return float(_get(key) or default)
    except ValueError:
        return default


def validate() -> None:
    """Raise if required env vars are missing."""
    token = _get("BOT_TOKEN")
    admin = _get("ADMIN_USER_ID")
    if not token:
        raise SystemExit("Missing BOT_TOKEN in .env")
    if not admin:
        raise SystemExit("Missing ADMIN_USER_ID in .env")
    try:
        int(admin)
    except ValueError:
        raise SystemExit("ADMIN_USER_ID must be a numeric Telegram user ID")


# Required
BOT_TOKEN: str = _get("BOT_TOKEN", "")
ADMIN_USER_ID: str = _get("ADMIN_USER_ID", "")

# Optional defaults
PING_DEFAULT_INTERVAL: float = _get_float("PING_DEFAULT_INTERVAL", 0.2)
PING_DEFAULT_COUNT: int = _get_int("PING_DEFAULT_COUNT", 10)

# Paths
def get_project_root() -> Path:
    return _PROJECT_ROOT


def get_env_path() -> Path:
    return _ENV_PATH


def get_jobs_path() -> Path:
    return _JOBS_PATH


def mask_token(token: str) -> str:
    """Return masked token (first 4 + ... + last 4) for display."""
    if not token or len(token) < 12:
        return "****"
    return f"{token[:4]}...{token[-4:]}"
