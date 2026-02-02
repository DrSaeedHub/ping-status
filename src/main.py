"""Entry point: load .env, start bot and scheduler."""
import sys
import traceback

from src.config import ADMIN_USER_ID, validate
from src.bot import create_bot
from src.error_reporting import send_error, set_send_target
from src.scheduler import get_next_run_times, reload_scheduler, run_job_now, start_scheduler

_scheduler = None
_send_message_func = None


def _reload_scheduler() -> None:
    global _scheduler, _send_message_func
    if _scheduler and _send_message_func:
        reload_scheduler(_scheduler, _send_message_func, int(ADMIN_USER_ID))


def get_scheduler_reloader():
    """Return a callable that reloads scheduler jobs (for bot after CRUD)."""
    return _reload_scheduler


def main() -> None:
    validate()
    admin_id = int(ADMIN_USER_ID)

    def _get_next_times():
        return get_next_run_times()

    def _run_job_now(name: str):
        if _scheduler and _send_message_func:
            run_job_now(_scheduler, name, _send_message_func, admin_id, skip_progress=True)

    bot, _ = create_bot(
        send_message_callback=None,
        run_job_now_callback=_run_job_now,
        get_next_run_times_callback=_get_next_times,
    )
    global _send_message_func, _scheduler
    _send_message_func = bot.send_message
    set_send_target(bot.send_message, admin_id)
    _scheduler = start_scheduler(bot.send_message, admin_id)
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        send_error(e, "main: infinity_polling")
        raise
    finally:
        if _scheduler:
            _scheduler.shutdown(wait=False)


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except SystemExit as e:
        if e.code and e.code != 0:
            print(e, file=sys.stderr)
        sys.exit(e.code if isinstance(e.code, int) else 1)
    except Exception as e:
        send_error(e, "main: uncaught")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
