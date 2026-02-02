# Ping Status

A Python Telegram bot that runs configurable ping jobs on a Linux (Ubuntu) server and sends detailed reports to the admin. Jobs are stored in `jobs.json`; config in `.env`. The bot responds only to the admin user ID and uses inline keyboards only.

## One-line install (Ubuntu)

```bash
bash <(curl -Ls https://raw.githubusercontent.com/DrSaeedHub/ping-status/main/install.sh)
```

Or using the script under `scripts/`:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/DrSaeedHub/ping-status/main/scripts/install.sh)
```

Or clone and run:

```bash
git clone https://github.com/DrSaeedHub/ping-status.git && cd ping-status && bash install.sh
```

The install script offers four options:

1. **Install** – First-time install: installs system and Python dependencies, prompts for Telegram Bot Token and Admin User ID, writes `.env`, creates a systemd user service, and starts the app.
2. **Fresh install** – Reinstall from scratch (keeps backup of `.env` if present).
3. **Update** – Pull latest code, reinstall Python deps, keep `.env` and `jobs.json`, restart service.
4. **Uninstall** – Stop service, remove systemd unit, remove install directory.

Install directory: `$HOME/ping-status` (override with `INSTALL_DIR`). When run via curl, the script downloads the repo into that directory.

## Environment variables (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | Yes | Telegram Bot Token from [@BotFather](https://t.me/BotFather). |
| `ADMIN_USER_ID` | Yes | Numeric Telegram user ID; only this user can use the bot. |
| `PING_DEFAULT_INTERVAL` | No | Default ping interval in seconds (e.g. `0.2`). |
| `PING_DEFAULT_COUNT` | No | Default ping count (e.g. `10`). |

You can edit `.env` manually or use the bot’s **Config** menu to change the default interval/count.

## Usage (Telegram bot)

- **/start**, **/help** – Show main menu (Jobs, Config, Help).
- **Jobs** – List jobs; add, edit, or delete jobs by name. Each job has: name, target IP/host, interval (seconds), count, and schedule (run every N minutes).
- **Config** – View current config (token masked), set default interval and count.

All buttons are inline. When you tap a button, the previous message is deleted and a new one is sent so the chat stays clean.

Ping is run as: `ping -c <count> -i <interval_sec> <target>`. Example: `ping -c 1000 -i 0.01 1.1.1.1`. On Linux, interval &lt; 0.2 seconds may require root.

## Run manually (no systemd)

```bash
cd /path/to/ping-status
source venv/bin/activate
python -m src.main
```

## License

MIT.
