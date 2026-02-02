"""Send errors to admin. Call set_send_target() at startup, then send_error() in every except."""
import sys
import traceback
from typing import Callable

# Set from main after bot is created: (send_message_func, admin_chat_id)
_send_func: Callable[[int, str], None] | None = None
_admin_id: int | None = None

# Telegram message length limit
_MAX_MESSAGE_LEN = 4096


def set_send_target(send_message_func: Callable[[int, str], None], admin_chat_id: int) -> None:
    """Call once at startup so send_error can deliver to admin."""
    global _send_func, _admin_id
    _send_func = send_message_func
    _admin_id = admin_chat_id


def send_error(exc: BaseException, context: str = "") -> None:
    """
    Format exception + traceback and send to admin. Call from every except block.
    If target not set or send fails, prints to stderr.
    """
    try:
        lines = ["Ping Status — Error"]
        if context:
            lines.append(f"Context: {context}")
        lines.append(f"{type(exc).__name__}: {exc}")
        lines.append("")
        lines.append(traceback.format_exc())
        text = "\n".join(lines).strip()
        if len(text) > _MAX_MESSAGE_LEN:
            text = text[: _MAX_MESSAGE_LEN - 20] + "\n… (truncated)"
        if _send_func is not None and _admin_id is not None:
            _send_func(_admin_id, text)
        else:
            print(text, file=sys.stderr)
    except Exception as e:
        print(f"send_error failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
