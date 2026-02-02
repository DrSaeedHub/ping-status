"""Telegram bot: inline-only keyboards, delete-then-send on button click, job CRUD, config."""
import re
import threading

import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import (
    ADMIN_USER_ID,
    BOT_TOKEN,
    get_env_path,
    mask_token,
)
from src.jobs_store import (
    add_job,
    delete_job,
    get_job_by_name,
    load_jobs,
    save_jobs,
    update_job,
)

# Max callback_data length
CB_MAX = 64
# In-memory state for multi-step flows (chat_id -> dict)
_state: dict[int, dict] = {}
_state_lock = threading.Lock()


def _is_admin(user_id: int) -> bool:
    return str(user_id) == ADMIN_USER_ID


def _delete_and_send(bot: telebot.TeleBot, chat_id: int, message_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Delete the message and send a new one (clean chat)."""
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass
    bot.send_message(chat_id, text, reply_markup=reply_markup)


def _main_menu_markup() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(
        InlineKeyboardButton("Jobs", callback_data="menu_jobs"),
        InlineKeyboardButton("Config", callback_data="menu_cfg"),
        InlineKeyboardButton("Help", callback_data="menu_help"),
    )
    return m


def _jobs_list_markup() -> tuple[str, InlineKeyboardMarkup]:
    jobs = load_jobs()
    lines = ["Ping jobs:\n"] if jobs else ["No jobs yet.\n"]
    for j in jobs:
        name = j.get("name", "?")
        target = j.get("target", "?")
        interval = j.get("interval_sec", "?")
        count = j.get("count", "?")
        sched = j.get("schedule_minutes", "?")
        lines.append(f"• {name}: {target} (-i {interval} -c {count}) every {sched} min")
    text = "\n".join(lines)
    m = InlineKeyboardMarkup()
    for j in jobs:
        name = j.get("name", "?")
        cb_edit = f"job_edit:{name}"[:CB_MAX]
        cb_del = f"job_del:{name}"[:CB_MAX]
        m.row(
            InlineKeyboardButton(f"Edit {name}", callback_data=cb_edit),
            InlineKeyboardButton(f"Delete {name}", callback_data=cb_del),
        )
    m.row(InlineKeyboardButton("Add job", callback_data="job_add"))
    m.row(InlineKeyboardButton("Back", callback_data="menu_main"))
    return text, m


def _job_edit_field_markup(job_name: str) -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    for label, field in [("Target", "target"), ("Interval (s)", "interval_sec"), ("Count", "count"), ("Schedule (min)", "schedule_minutes")]:
        cb = f"editfield:{job_name}:{field}"[:CB_MAX]
        m.row(InlineKeyboardButton(label, callback_data=cb))
    m.row(InlineKeyboardButton("Back to jobs", callback_data="menu_jobs"))
    return m


def _config_text() -> str:
    env_path = get_env_path()
    token_masked = mask_token(BOT_TOKEN) if BOT_TOKEN else "****"
    lines = [
        "Config",
        f"BOT_TOKEN: {token_masked}",
        f"ADMIN_USER_ID: {ADMIN_USER_ID}",
        f".env path: {env_path}",
    ]
    try:
        from src import config as config_module
        lines.append(f"PING_DEFAULT_INTERVAL: {config_module.PING_DEFAULT_INTERVAL}")
        lines.append(f"PING_DEFAULT_COUNT: {config_module.PING_DEFAULT_COUNT}")
    except Exception:
        pass
    return "\n".join(lines)


def _config_markup() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(InlineKeyboardButton("Set default interval", callback_data="cfg_set_interval"))
    m.row(InlineKeyboardButton("Set default count", callback_data="cfg_set_count"))
    m.row(InlineKeyboardButton("Back", callback_data="menu_main"))
    return m


def _help_text() -> str:
    return (
        "Ping Status\n\n"
        "• Jobs: create, edit, delete ping jobs. Each job runs every N minutes and sends a report here.\n"
        "• Config: view .env (token masked), set default interval/count for new jobs.\n"
        "• Ping command: ping -c <count> -i <interval_sec> <target>\n"
        "On Linux, interval < 0.2 may require root."
    )


def _set_state(chat_id: int, data: dict) -> None:
    with _state_lock:
        _state[chat_id] = data


def _get_state(chat_id: int) -> dict | None:
    with _state_lock:
        return _state.get(chat_id)


def _clear_state(chat_id: int) -> None:
    with _state_lock:
        _state.pop(chat_id, None)


def _update_env_key(key: str, value: str) -> None:
    path = get_env_path()
    if not path.exists():
        path.write_text(f"{key}={value}\n", encoding="utf-8")
        from dotenv import load_dotenv
        load_dotenv(path)
        import src.config as config_module
        if key == "PING_DEFAULT_INTERVAL":
            try:
                config_module.PING_DEFAULT_INTERVAL = float(value)
            except ValueError:
                pass
        elif key == "PING_DEFAULT_COUNT":
            try:
                config_module.PING_DEFAULT_COUNT = int(value)
            except ValueError:
                pass
        return
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    # Reload in-memory config
    from dotenv import load_dotenv
    load_dotenv(path)
    import src.config as config_module
    if key == "PING_DEFAULT_INTERVAL":
        try:
            config_module.PING_DEFAULT_INTERVAL = float(value)
        except ValueError:
            pass
    elif key == "PING_DEFAULT_COUNT":
        try:
            config_module.PING_DEFAULT_COUNT = int(value)
        except ValueError:
            pass


def create_bot(send_message_callback=None):
    """
    Create and configure the TeleBot. send_message_callback(chat_id, text) is used
    by the scheduler to send ping reports; if None, bot.send_message is used.
    """
    bot = telebot.TeleBot(BOT_TOKEN)

    def send_to_admin(text: str) -> None:
        if send_message_callback:
            send_message_callback(int(ADMIN_USER_ID), text)
        else:
            bot.send_message(int(ADMIN_USER_ID), text)

    @bot.message_handler(commands=["start", "help"])
    def cmd_start_help(msg):
        if not _is_admin(msg.from_user.id):
            bot.reply_to(msg, "Unauthorized")
            return
        text = "Ping Status\n\nChoose an option:"
        bot.send_message(msg.chat.id, text, reply_markup=_main_menu_markup())

    @bot.callback_query_handler(func=lambda c: True)
    def on_callback(c):
        if not _is_admin(c.from_user.id):
            try:
                bot.answer_callback_query(c.id, "Unauthorized")
            except Exception:
                pass
            return
        chat_id = c.message.chat.id
        msg_id = c.message.message_id
        data = c.data or ""

        # Main menu
        if data == "menu_main":
            _delete_and_send(bot, chat_id, msg_id, "Choose an option:", _main_menu_markup())
            return
        if data == "menu_jobs":
            text, mk = _jobs_list_markup()
            _delete_and_send(bot, chat_id, msg_id, text, mk)
            return
        if data == "menu_cfg":
            _delete_and_send(bot, chat_id, msg_id, _config_text(), _config_markup())
            return
        if data == "menu_help":
            _delete_and_send(bot, chat_id, msg_id, _help_text(), InlineKeyboardMarkup().row(InlineKeyboardButton("Back", callback_data="menu_main")))
            return

        # Add job flow
        if data == "job_add":
            _set_state(chat_id, {"flow": "addjob", "step": "name"})
            _delete_and_send(bot, chat_id, msg_id, "Send job name (e.g. cloudflare):", InlineKeyboardMarkup().row(InlineKeyboardButton("Cancel", callback_data="menu_jobs")))
            return

        # Edit job: pick field
        if data.startswith("job_edit:"):
            job_name = data[9:].strip()
            job = get_job_by_name(job_name)
            if not job:
                _delete_and_send(bot, chat_id, msg_id, f"Job '{job_name}' not found.", _main_menu_markup())
                return
            _set_state(chat_id, {"flow": "edit", "job_name": job_name})
            _delete_and_send(bot, chat_id, msg_id, f"Edit job '{job_name}'. Choose field:", _job_edit_field_markup(job_name))
            return

        # Edit field
        if data.startswith("editfield:"):
            parts = data.split(":", 2)
            if len(parts) < 3:
                text, mk = _jobs_list_markup()
                _delete_and_send(bot, chat_id, msg_id, text, mk)
                return
            job_name, field = parts[1], parts[2]
            _set_state(chat_id, {"flow": "edit_field", "job_name": job_name, "field": field})
            _delete_and_send(bot, chat_id, msg_id, f"Send new value for '{field}' (job: {job_name}):", InlineKeyboardMarkup().row(InlineKeyboardButton("Cancel", callback_data="menu_jobs")))
            return

        # Delete job: confirm
        if data.startswith("job_del:"):
            job_name = data[8:].strip()
            _set_state(chat_id, {"flow": "del_confirm", "job_name": job_name})
            m = InlineKeyboardMarkup()
            m.row(InlineKeyboardButton("Yes, delete", callback_data=f"del_yes:{job_name}"[:CB_MAX]))
            m.row(InlineKeyboardButton("Cancel", callback_data="menu_jobs"))
            _delete_and_send(bot, chat_id, msg_id, f"Delete job '{job_name}'?", m)
            return
        if data.startswith("del_yes:"):
            job_name = data[7:].strip()
            if delete_job(job_name):
                _delete_and_send(bot, chat_id, msg_id, f"Deleted job '{job_name}'.", _main_menu_markup())
            else:
                _delete_and_send(bot, chat_id, msg_id, f"Job '{job_name}' not found.", _main_menu_markup())
            _clear_state(chat_id)
            if send_message_callback:
                try:
                    from src.main import get_scheduler_reloader
                    reloader = get_scheduler_reloader()
                    if reloader:
                        reloader()
                except Exception:
                    pass
            return

        # Config set
        if data == "cfg_set_interval":
            _set_state(chat_id, {"flow": "cfg", "key": "PING_DEFAULT_INTERVAL"})
            _delete_and_send(bot, chat_id, msg_id, "Send new default interval (seconds, e.g. 0.2):", InlineKeyboardMarkup().row(InlineKeyboardButton("Cancel", callback_data="menu_cfg")))
            return
        if data == "cfg_set_count":
            _set_state(chat_id, {"flow": "cfg", "key": "PING_DEFAULT_COUNT"})
            _delete_and_send(bot, chat_id, msg_id, "Send new default count (e.g. 10):", InlineKeyboardMarkup().row(InlineKeyboardButton("Cancel", callback_data="menu_cfg")))
            return

        try:
            bot.answer_callback_query(c.id)
        except Exception:
            pass

    @bot.message_handler(func=lambda m: True)
    def on_message(msg):
        if not _is_admin(msg.from_user.id):
            bot.reply_to(msg, "Unauthorized")
            return
        chat_id = msg.chat.id
        text = (msg.text or "").strip()
        state = _get_state(chat_id)

        # Add job: collect name -> target -> interval -> count -> schedule
        if state and state.get("flow") == "addjob":
            step = state.get("step", "name")
            if step == "name":
                if not re.match(r"^[a-zA-Z0-9_. -]+$", text) or len(text) > 32:
                    bot.reply_to(msg, "Invalid name. Use letters, numbers, _ - . or space. Max 32 chars.")
                    return
                if get_job_by_name(text):
                    bot.reply_to(msg, "A job with this name already exists.")
                    return
                _set_state(chat_id, {**state, "step": "target", "name": text})
                bot.reply_to(msg, f"Job name set to '{text}'. Send target IP or hostname:")
                return
            if step == "target":
                _set_state(chat_id, {**state, "step": "interval", "target": text})
                bot.reply_to(msg, "Send interval in seconds (e.g. 0.01 or 0.2):")
                return
            if step == "interval":
                try:
                    iv = float(text)
                    if iv <= 0 or iv > 3600:
                        raise ValueError("out of range")
                except ValueError:
                    bot.reply_to(msg, "Send a positive number (e.g. 0.01 or 0.2):")
                    return
                _set_state(chat_id, {**state, "step": "count", "interval_sec": iv})
                bot.reply_to(msg, "Send ping count (e.g. 1000):")
                return
            if step == "count":
                try:
                    cnt = int(text)
                    if cnt < 1 or cnt > 100000:
                        raise ValueError("out of range")
                except ValueError:
                    bot.reply_to(msg, "Send a positive integer (1–100000):")
                    return
                _set_state(chat_id, {**state, "step": "schedule", "count": cnt})
                bot.reply_to(msg, "Send schedule: run every N minutes (e.g. 5):")
                return
            if step == "schedule":
                try:
                    sched = int(text)
                    if sched < 1 or sched > 10080:  # max 1 week
                        raise ValueError("out of range")
                except ValueError:
                    bot.reply_to(msg, "Send a positive integer (minutes, 1–10080):")
                    return
                job = {
                    "name": state["name"],
                    "target": state["target"],
                    "interval_sec": state["interval_sec"],
                    "count": state["count"],
                    "schedule_minutes": sched,
                }
                if add_job(job):
                    _clear_state(chat_id)
                    bot.reply_to(msg, f"Job '{job['name']}' added.")
                    if send_message_callback:
                        try:
                            from src.main import get_scheduler_reloader
                            r = get_scheduler_reloader()
                            if r:
                                r()
                        except Exception:
                            pass
                    text2, mk = _jobs_list_markup()
                    bot.send_message(chat_id, text2, reply_markup=mk)
                else:
                    bot.reply_to(msg, "Failed to add job (name may already exist).")
                return

        # Edit field
        if state and state.get("flow") == "edit_field":
            job_name = state.get("job_name")
            field = state.get("field")
            job = get_job_by_name(job_name)
            if not job:
                _clear_state(chat_id)
                bot.reply_to(msg, "Job not found.")
                return
            if field == "target":
                val = text
            elif field == "interval_sec":
                try:
                    val = float(text)
                    if val <= 0 or val > 3600:
                        raise ValueError()
                except ValueError:
                    bot.reply_to(msg, "Send a positive number (e.g. 0.01):")
                    return
            elif field == "count":
                try:
                    val = int(text)
                    if val < 1 or val > 100000:
                        raise ValueError()
                except ValueError:
                    bot.reply_to(msg, "Send an integer 1–100000:")
                    return
            elif field == "schedule_minutes":
                try:
                    val = int(text)
                    if val < 1 or val > 10080:
                        raise ValueError()
                except ValueError:
                    bot.reply_to(msg, "Send minutes (1–10080):")
                    return
            else:
                _clear_state(chat_id)
                text2, mk = _jobs_list_markup()
                bot.send_message(chat_id, text2, reply_markup=mk)
                return
            update_job(job_name, {field: val})
            _clear_state(chat_id)
            bot.reply_to(msg, f"Updated {field}.")
            if send_message_callback:
                try:
                    from src.main import get_scheduler_reloader
                    r = get_scheduler_reloader()
                    if r:
                        r()
                except Exception:
                    pass
            text2, mk = _jobs_list_markup()
            bot.send_message(chat_id, text2, reply_markup=mk)
            return

        # Config: set key
        if state and state.get("flow") == "cfg":
            key = state.get("key")
            if key == "PING_DEFAULT_INTERVAL":
                try:
                    float(text)
                except ValueError:
                    bot.reply_to(msg, "Send a number (e.g. 0.2):")
                    return
            elif key == "PING_DEFAULT_COUNT":
                try:
                    int(text)
                except ValueError:
                    bot.reply_to(msg, "Send an integer (e.g. 10):")
                    return
            _update_env_key(key, text)
            _clear_state(chat_id)
            bot.reply_to(msg, f"Updated {key}.")
            _delete_and_send(bot, chat_id, msg.message_id, _config_text(), _config_markup())
            return

        # No state: show main menu (do not delete user's message)
        bot.send_message(chat_id, "Choose an option:", reply_markup=_main_menu_markup())

    return bot, send_to_admin
