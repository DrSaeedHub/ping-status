"""Telegram bot: inline-only keyboards, delete-then-send on button click, job CRUD, config."""
import re
import threading
from datetime import datetime
from html import escape
from typing import Callable

import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import (
    ADMIN_USER_ID,
    BOT_TOKEN,
    get_env_path,
    mask_token,
)
from src.error_reporting import send_error
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

_FIELD_LABELS = {
    "target": "Target",
    "interval_sec": "Interval (s)",
    "count": "Packet Count",
    "schedule_minutes": "Schedule (min)",
}
_CONFIG_LABELS = {
    "PING_DEFAULT_INTERVAL": "Default Interval",
    "PING_DEFAULT_COUNT": "Default Count",
}


def _h(value: object) -> str:
    return escape(str(value), quote=False)


def _send_html(
    bot: telebot.TeleBot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")


def _reply_html(bot: telebot.TeleBot, msg, text: str) -> None:
    bot.reply_to(msg, text, parse_mode="HTML")


def _field_label(field: str) -> str:
    return _FIELD_LABELS.get(field, field)


def _config_label(key: str) -> str:
    return _CONFIG_LABELS.get(key, key)


def _fmt_num(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _is_admin(user_id: int) -> bool:
    return str(user_id) == ADMIN_USER_ID


def _delete_and_send(bot: telebot.TeleBot, chat_id: int, message_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Delete the message and send a new one (clean chat)."""
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        send_error(e, "bot: delete_message")
    try:
        _send_html(bot, chat_id, text, reply_markup=reply_markup)
    except Exception as e:
        send_error(e, "bot: send_message in _delete_and_send")
        raise


def _main_menu_markup() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(
        InlineKeyboardButton("🗂️ Jobs", callback_data="menu_jobs"),
        InlineKeyboardButton("⚙️ Settings", callback_data="menu_cfg"),
        InlineKeyboardButton("❓ Help", callback_data="menu_help"),
    )
    return m


def _format_run_time(dt_or_iso: datetime | str | None) -> str:
    """Format datetime or ISO string for display; return '—' if missing."""
    if dt_or_iso is None:
        return "—"
    if isinstance(dt_or_iso, str):
        try:
            s = dt_or_iso.replace("Z", "+00:00")
            dt_or_iso = datetime.fromisoformat(s)
        except (ValueError, TypeError) as e:
            send_error(e, "bot: _format_run_time fromisoformat")
            return "—"
    try:
        return dt_or_iso.strftime("%d %b %H:%M")
    except (ValueError, TypeError) as e:
        send_error(e, "bot: _format_run_time strftime")
        return "—"


def _jobs_list_markup(next_run_times: dict | None = None) -> tuple[str, InlineKeyboardMarkup]:
    jobs = load_jobs()
    next_run_times = next_run_times or {}
    if not jobs:
        text = "<b>🗂️ Ping Jobs</b>\nNo jobs yet. Tap ➕ Add Job to create one."
    else:
        lines = [f"<b>🗂️ Ping Jobs</b>", f"Total: <b>{len(jobs)}</b>", ""]
        for j in jobs:
            name = j.get("name", "?")
            target = j.get("target", "?")
            interval = _fmt_num(j.get("interval_sec", "?"))
            count = j.get("count", "?")
            sched = j.get("schedule_minutes", "?")
            last_run = _format_run_time(j.get("last_run_at"))
            next_run = _format_run_time(next_run_times.get(name))
            lines.append(f"• <b>{_h(name)}</b>")
            lines.append(f"🎯 <b>Target:</b> {_h(target)}")
            lines.append(f"📦 <b>Test:</b> {count} packets (interval {interval}s)")
            lines.append(f"🗓️ <b>Schedule:</b> every {sched} min")
            lines.append(f"🕘 <b>Last:</b> {last_run} • <b>Next:</b> {next_run}")
            lines.append("")
        text = "\n".join(lines).rstrip()
    m = InlineKeyboardMarkup()
    for j in jobs:
        name = j.get("name", "?")
        cb_edit = f"job_edit:{name}"[:CB_MAX]
        cb_del = f"job_del:{name}"[:CB_MAX]
        cb_run = f"job_run:{name}"[:CB_MAX]
        m.row(
            InlineKeyboardButton("▶️ Run", callback_data=cb_run),
            InlineKeyboardButton("✏️ Edit", callback_data=cb_edit),
            InlineKeyboardButton("🗑️ Delete", callback_data=cb_del),
        )
    m.row(InlineKeyboardButton("➕ Add Job", callback_data="job_add"))
    m.row(InlineKeyboardButton("⬅️ Back", callback_data="menu_main"))
    return text, m


def _job_edit_field_markup(job_name: str) -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    for label, field in [("🎯 Target", "target"), ("⏱️ Interval (s)", "interval_sec"), ("📦 Packet Count", "count"), ("🗓️ Schedule (min)", "schedule_minutes")]:
        cb = f"editfield:{job_name}:{field}"[:CB_MAX]
        m.row(InlineKeyboardButton(label, callback_data=cb))
    m.row(InlineKeyboardButton("⬅️ Back to Jobs", callback_data="menu_jobs"))
    return m


def _config_text() -> str:
    env_path = get_env_path()
    token_masked = mask_token(BOT_TOKEN) if BOT_TOKEN else "****"
    lines = [
        "<b>⚙️ Settings</b>",
        f"• <b>BOT_TOKEN:</b> <code>{_h(token_masked)}</code>",
        f"• <b>ADMIN_USER_ID:</b> <code>{_h(ADMIN_USER_ID)}</code>",
        f"• <b>.env Path:</b> <code>{_h(env_path)}</code>",
    ]
    try:
        from src import config as config_module
        lines.append(f"• <b>Default Interval:</b> {_fmt_num(config_module.PING_DEFAULT_INTERVAL)} s")
        lines.append(f"• <b>Default Count:</b> {config_module.PING_DEFAULT_COUNT}")
    except Exception as e:
        send_error(e, "bot: _config_text config_module")
    return "\n".join(lines)


def _config_markup() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(InlineKeyboardButton("⏱️ Default Interval", callback_data="cfg_set_interval"))
    m.row(InlineKeyboardButton("📦 Default Count", callback_data="cfg_set_count"))
    m.row(InlineKeyboardButton("⬅️ Back", callback_data="menu_main"))
    return m


def _help_text() -> str:
    return (
        "<b>❓ Help</b>\n"
        "• <b>Jobs:</b> Create, edit, and delete ping jobs. Each job runs every N minutes and sends a report here.\n"
        "• <b>Settings:</b> View your .env (token masked) and set defaults for new jobs.\n"
        "• <b>Ping command:</b> <code>ping -c &lt;count&gt; -i &lt;interval_sec&gt; &lt;target&gt;</code>\n"
        "On Linux, intervals below 0.2s may require root."
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
            except ValueError as e:
                send_error(e, "bot: _update_env_key PING_DEFAULT_INTERVAL (new file)")
        elif key == "PING_DEFAULT_COUNT":
            try:
                config_module.PING_DEFAULT_COUNT = int(value)
            except ValueError as e:
                send_error(e, "bot: _update_env_key PING_DEFAULT_COUNT (new file)")
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
        except ValueError as e:
            send_error(e, "bot: _update_env_key PING_DEFAULT_INTERVAL")
    elif key == "PING_DEFAULT_COUNT":
        try:
            config_module.PING_DEFAULT_COUNT = int(value)
        except ValueError as e:
            send_error(e, "bot: _update_env_key PING_DEFAULT_COUNT")


def create_bot(
    send_message_callback=None,
    run_job_now_callback: Callable[[str], None] | None = None,
    get_next_run_times_callback: Callable[[], dict] | None = None,
):
    """
    Create and configure the TeleBot. send_message_callback(chat_id, text) is used
    by the scheduler to send ping reports; if None, bot.send_message is used.
    run_job_now_callback(name) runs a job once (called from "Run now").
    get_next_run_times_callback() returns {job_name: next_run_time} for the jobs list.
    """
    bot = telebot.TeleBot(BOT_TOKEN)

    def _get_next_times() -> dict:
        return get_next_run_times_callback() if get_next_run_times_callback else {}

    def _jobs_list_with_times():
        return _jobs_list_markup(_get_next_times())

    def send_to_admin(text: str) -> None:
        if send_message_callback:
            send_message_callback(int(ADMIN_USER_ID), text)
        else:
            _send_html(bot, int(ADMIN_USER_ID), text)

    @bot.message_handler(commands=["start", "help"])
    def cmd_start_help(msg):
        if not _is_admin(msg.from_user.id):
            _reply_html(bot, msg, "🚫 <b>Access denied.</b> This bot is private.")
            return
        text = "<b>📡 Ping Status</b>\nChoose an option below:"
        _send_html(bot, msg.chat.id, text, reply_markup=_main_menu_markup())

    @bot.callback_query_handler(func=lambda c: True)
    def on_callback(c):
        if not _is_admin(c.from_user.id):
            try:
                bot.answer_callback_query(c.id, "Access denied.")
            except Exception as e:
                send_error(e, "bot: answer_callback_query Unauthorized")
            return
        chat_id = c.message.chat.id
        msg_id = c.message.message_id
        data = c.data or ""

        # Main menu
        if data == "menu_main":
            _delete_and_send(bot, chat_id, msg_id, "Choose an option below:", _main_menu_markup())
            return
        if data == "menu_jobs":
            text, mk = _jobs_list_with_times()
            _delete_and_send(bot, chat_id, msg_id, text, mk)
            return
        if data == "menu_cfg":
            _delete_and_send(bot, chat_id, msg_id, _config_text(), _config_markup())
            return
        if data == "menu_help":
            _delete_and_send(bot, chat_id, msg_id, _help_text(), InlineKeyboardMarkup().row(InlineKeyboardButton("⬅️ Back", callback_data="menu_main")))
            return

        # Add job flow
        if data == "job_add":
            _set_state(chat_id, {"flow": "addjob", "step": "name"})
            _delete_and_send(
                bot,
                chat_id,
                msg_id,
                "✍️ <b>Job name</b>\nSend a short name (e.g. <code>cloudflare</code>):",
                InlineKeyboardMarkup().row(InlineKeyboardButton("✖️ Cancel", callback_data="menu_jobs")),
            )
            return

        # Edit job: pick field
        if data.startswith("job_edit:"):
            job_name = data[9:].strip()
            job = get_job_by_name(job_name)
            if not job:
                _delete_and_send(bot, chat_id, msg_id, f"❌ <b>Job not found:</b> <code>{_h(job_name)}</code>", _main_menu_markup())
                return
            _set_state(chat_id, {"flow": "edit", "job_name": job_name})
            _delete_and_send(
                bot,
                chat_id,
                msg_id,
                f"✏️ <b>Edit Job:</b> <code>{_h(job_name)}</code>\nChoose what to change:",
                _job_edit_field_markup(job_name),
            )
            return

        # Edit field
        if data.startswith("editfield:"):
            parts = data.split(":", 2)
            if len(parts) < 3:
                text, mk = _jobs_list_with_times()
                _delete_and_send(bot, chat_id, msg_id, text, mk)
                return
            job_name, field = parts[1], parts[2]
            _set_state(chat_id, {"flow": "edit_field", "job_name": job_name, "field": field})
            field_label = _field_label(field)
            _delete_and_send(
                bot,
                chat_id,
                msg_id,
                f"✍️ <b>New value</b>\nSend a new value for <b>{_h(field_label)}</b> (job: <code>{_h(job_name)}</code>):",
                InlineKeyboardMarkup().row(InlineKeyboardButton("✖️ Cancel", callback_data="menu_jobs")),
            )
            return

        # Delete job: confirm
        if data.startswith("job_run:"):
            job_name = data[8:].strip()
            try:
                bot.answer_callback_query(c.id, "Running…")
            except Exception as e:
                send_error(e, "bot: answer_callback_query Running job")
            _send_html(bot, chat_id, f"▶️ <b>Running now:</b> <code>{_h(job_name)}</code>")
            if run_job_now_callback:
                def _run():
                    run_job_now_callback(job_name)
                t = threading.Thread(target=_run, daemon=True)
                t.start()
            return
        if data.startswith("job_del:"):
            job_name = data[8:].strip()
            _set_state(chat_id, {"flow": "del_confirm", "job_name": job_name})
            m = InlineKeyboardMarkup()
            m.row(InlineKeyboardButton("🗑️ Yes, delete", callback_data=f"del_yes:{job_name}"[:CB_MAX]))
            m.row(InlineKeyboardButton("✖️ Cancel", callback_data="menu_jobs"))
            _delete_and_send(
                bot,
                chat_id,
                msg_id,
                f"🗑️ <b>Delete job?</b>\nThis will remove <code>{_h(job_name)}</code>.",
                m,
            )
            return
        if data.startswith("del_yes:"):
            job_name = data[7:].strip()
            if delete_job(job_name):
                _delete_and_send(bot, chat_id, msg_id, f"✅ <b>Job deleted:</b> <code>{_h(job_name)}</code>", _main_menu_markup())
            else:
                _delete_and_send(bot, chat_id, msg_id, f"❌ <b>Job not found:</b> <code>{_h(job_name)}</code>", _main_menu_markup())
            _clear_state(chat_id)
            if send_message_callback:
                try:
                    from src.main import get_scheduler_reloader
                    reloader = get_scheduler_reloader()
                    if reloader:
                        reloader()
                except Exception as e:
                    send_error(e, "bot: get_scheduler_reloader after del_yes")
            return

        # Config set
        if data == "cfg_set_interval":
            _set_state(chat_id, {"flow": "cfg", "key": "PING_DEFAULT_INTERVAL"})
            _delete_and_send(
                bot,
                chat_id,
                msg_id,
                "⏱️ <b>Default interval</b>\nSend seconds between packets (e.g. 0.2):",
                InlineKeyboardMarkup().row(InlineKeyboardButton("✖️ Cancel", callback_data="menu_cfg")),
            )
            return
        if data == "cfg_set_count":
            _set_state(chat_id, {"flow": "cfg", "key": "PING_DEFAULT_COUNT"})
            _delete_and_send(
                bot,
                chat_id,
                msg_id,
                "📦 <b>Default count</b>\nSend packets to send by default (e.g. 10):",
                InlineKeyboardMarkup().row(InlineKeyboardButton("✖️ Cancel", callback_data="menu_cfg")),
            )
            return

        try:
            bot.answer_callback_query(c.id)
        except Exception as e:
            send_error(e, "bot: answer_callback_query")

    @bot.message_handler(func=lambda m: True)
    def on_message(msg):
        if not _is_admin(msg.from_user.id):
            _reply_html(bot, msg, "🚫 <b>Access denied.</b> This bot is private.")
            return
        chat_id = msg.chat.id
        text = (msg.text or "").strip()
        state = _get_state(chat_id)

        # Add job: collect name -> target -> interval -> count -> schedule
        if state and state.get("flow") == "addjob":
            step = state.get("step", "name")
            if step == "name":
                if not re.match(r"^[a-zA-Z0-9_. -]+$", text) or len(text) > 32:
                    _reply_html(
                        bot,
                        msg,
                        "⚠️ <b>Invalid name.</b> Use letters, numbers, space, <code>_</code>, <code>-</code>, or <code>.</code> (max 32).",
                    )
                    return
                if get_job_by_name(text):
                    _reply_html(bot, msg, "⚠️ <b>Name already used.</b> Please choose a different name.")
                    return
                _set_state(chat_id, {**state, "step": "target", "name": text})
                _reply_html(
                    bot,
                    msg,
                    f"✅ <b>Name saved:</b> <code>{_h(text)}</code>\n🎯 Send target IP or hostname:",
                )
                return
            if step == "target":
                _set_state(chat_id, {**state, "step": "interval", "target": text})
                _reply_html(
                    bot,
                    msg,
                    "⏱️ <b>Interval</b>\nSend seconds between packets (e.g. 0.01 or 0.2):",
                )
                return
            if step == "interval":
                try:
                    iv = float(text)
                    if iv <= 0 or iv > 3600:
                        raise ValueError("out of range")
                except ValueError as e:
                    send_error(e, "bot: add job interval")
                    _reply_html(
                        bot,
                        msg,
                        "⚠️ <b>Invalid interval.</b> Send a positive number (e.g. 0.01 or 0.2).",
                    )
                    return
                _set_state(chat_id, {**state, "step": "count", "interval_sec": iv})
                _reply_html(
                    bot,
                    msg,
                    "📦 <b>Packet count</b>\nHow many packets to send? (e.g. 1000)",
                )
                return
            if step == "count":
                try:
                    cnt = int(text)
                    if cnt < 1 or cnt > 100000:
                        raise ValueError("out of range")
                except ValueError as e:
                    send_error(e, "bot: add job count")
                    _reply_html(
                        bot,
                        msg,
                        "⚠️ <b>Invalid count.</b> Send an integer from 1 to 100000.",
                    )
                    return
                _set_state(chat_id, {**state, "step": "schedule", "count": cnt})
                _reply_html(
                    bot,
                    msg,
                    "🗓️ <b>Schedule</b>\nRun every N minutes (e.g. 5):",
                )
                return
            if step == "schedule":
                try:
                    sched = int(text)
                    if sched < 1 or sched > 10080:  # max 1 week
                        raise ValueError("out of range")
                except ValueError as e:
                    send_error(e, "bot: add job schedule")
                    _reply_html(
                        bot,
                        msg,
                        "⚠️ <b>Invalid schedule.</b> Send minutes between 1 and 10080.",
                    )
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
                    _reply_html(
                        bot,
                        msg,
                        f"✅ <b>Job added:</b> <code>{_h(job['name'])}</code>\n▶️ Running once now…",
                    )
                    if run_job_now_callback:
                        def _run_new_job():
                            run_job_now_callback(job["name"])
                        t = threading.Thread(target=_run_new_job, daemon=True)
                        t.start()
                    if send_message_callback:
                        try:
                            from src.main import get_scheduler_reloader
                            r = get_scheduler_reloader()
                            if r:
                                r()
                        except Exception as e:
                            send_error(e, "bot: get_scheduler_reloader after add_job")
                    text2, mk = _jobs_list_with_times()
                    _send_html(bot, chat_id, text2, reply_markup=mk)
                else:
                    _reply_html(bot, msg, "❌ <b>Couldn't add job.</b> The name might already exist.")
                return

        # Edit field
        if state and state.get("flow") == "edit_field":
            job_name = state.get("job_name")
            field = state.get("field")
            job = get_job_by_name(job_name)
            if not job:
                _clear_state(chat_id)
                _reply_html(bot, msg, "❌ <b>Job not found.</b>")
                return
            if field == "target":
                val = text
            elif field == "interval_sec":
                try:
                    val = float(text)
                    if val <= 0 or val > 3600:
                        raise ValueError()
                except ValueError as e:
                    send_error(e, "bot: edit field interval_sec")
                    _reply_html(bot, msg, "⚠️ <b>Invalid interval.</b> Send a positive number (e.g. 0.01).")
                    return
            elif field == "count":
                try:
                    val = int(text)
                    if val < 1 or val > 100000:
                        raise ValueError()
                except ValueError as e:
                    send_error(e, "bot: edit field count")
                    _reply_html(bot, msg, "⚠️ <b>Invalid count.</b> Send an integer from 1 to 100000.")
                    return
            elif field == "schedule_minutes":
                try:
                    val = int(text)
                    if val < 1 or val > 10080:
                        raise ValueError()
                except ValueError as e:
                    send_error(e, "bot: edit field schedule_minutes")
                    _reply_html(bot, msg, "⚠️ <b>Invalid schedule.</b> Send minutes between 1 and 10080.")
                    return
            else:
                _clear_state(chat_id)
                text2, mk = _jobs_list_with_times()
                _send_html(bot, chat_id, text2, reply_markup=mk)
                return
            update_job(job_name, {field: val})
            _clear_state(chat_id)
            field_label = _field_label(field)
            _reply_html(bot, msg, f"✅ <b>Updated:</b> {_h(field_label)}")
            if send_message_callback:
                try:
                    from src.main import get_scheduler_reloader
                    r = get_scheduler_reloader()
                    if r:
                        r()
                except Exception as e:
                    send_error(e, "bot: get_scheduler_reloader after update_job")
            text2, mk = _jobs_list_with_times()
            _send_html(bot, chat_id, text2, reply_markup=mk)
            return

        # Config: set key
        if state and state.get("flow") == "cfg":
            key = state.get("key")
            if key == "PING_DEFAULT_INTERVAL":
                try:
                    float(text)
                except ValueError as e:
                    send_error(e, "bot: cfg PING_DEFAULT_INTERVAL")
                    _reply_html(bot, msg, "⚠️ <b>Invalid number.</b> Send a number (e.g. 0.2).")
                    return
            elif key == "PING_DEFAULT_COUNT":
                try:
                    int(text)
                except ValueError as e:
                    send_error(e, "bot: cfg PING_DEFAULT_COUNT")
                    _reply_html(bot, msg, "⚠️ <b>Invalid count.</b> Send an integer (e.g. 10).")
                    return
            _update_env_key(key, text)
            _clear_state(chat_id)
            _reply_html(bot, msg, f"✅ <b>Updated:</b> {_h(_config_label(key))}")
            _delete_and_send(bot, chat_id, msg.message_id, _config_text(), _config_markup())
            return

        # No state: show main menu (do not delete user's message)
        _send_html(bot, chat_id, "Choose an option below:", reply_markup=_main_menu_markup())

    return bot, send_to_admin
