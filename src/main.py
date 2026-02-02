"""Entry point: load .env, start bot and scheduler."""
import sys

from src.config import ADMIN_USER_ID, validate
from src.bot import create_bot
from src.scheduler import reload_scheduler, start_scheduler

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
    bot, _ = create_bot(send_message_callback=None)
    global _send_message_func, _scheduler
    _send_message_func = bot.send_message
    _scheduler = start_scheduler(bot.send_message, int(ADMIN_USER_ID))
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        pass
    finally:
        if _scheduler:
            _scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
    sys.exit(0)
