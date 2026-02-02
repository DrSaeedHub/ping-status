#!/usr/bin/env bash
# Ping Status installer
# Target OS: Ubuntu. Options: 1. Install, 2. Fresh install, 3. Update, 4. Complete uninstall.
set -e

REPO_URL="${REPO_URL:-https://github.com/DrSaeedHub/ping-status}"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/ping-status}"
SERVICE_NAME="ping-status"

# Detect if we are running from repo (have src/ and requirements.txt)
in_repo() {
  [ -d "src" ] && [ -f "requirements.txt" ] && [ -f "install.sh" ]
}

# Ensure we're in INSTALL_DIR with app code (fetch if needed)
ensure_app() {
  mkdir -p "$INSTALL_DIR"
  cd "$INSTALL_DIR"
  if ! in_repo; then
    echo "Downloading repository..."
    if command -v git &>/dev/null; then
      if [ -d ".git" ]; then
        git fetch origin "$REPO_BRANCH" || true
        git checkout "$REPO_BRANCH" 2>/dev/null || true
        git pull origin "$REPO_BRANCH" 2>/dev/null || true
      else
        rm -rf ./*
        git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" .
      fi
    else
      curl -sL "${REPO_URL}/archive/refs/heads/${REPO_BRANCH}.zip" -o main.zip
      unzip -o main.zip
      rm -f main.zip
      mv "ping-status-${REPO_BRANCH}"/* .
      rm -rf "ping-status-${REPO_BRANCH}"
    fi
  fi
  cd "$INSTALL_DIR"
}

# Install system dependencies (Ubuntu)
install_system_deps() {
  echo "Installing system dependencies (apt)..."
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3 python3-venv python3-pip curl iputils-ping
  if ! in_repo; then
    sudo apt-get install -y -qq git unzip 2>/dev/null || true
  fi
}

# Create venv and install Python deps
install_python_deps() {
  cd "$INSTALL_DIR"
  if [ ! -d "venv" ]; then
    python3 -m venv venv
  fi
  ./venv/bin/pip install -q --upgrade pip
  ./venv/bin/pip install -q -r requirements.txt
}

# Prompt for BOT_TOKEN (no echo)
read_token() {
  local v
  read -rsp "Telegram Bot Token: " v
  echo
  echo "$v"
}

# Prompt for ADMIN_USER_ID
read_admin_id() {
  local v
  read -rp "Admin User ID (numeric): " v
  echo "$v"
}

# Write .env
write_env() {
  local token="$1"
  local admin_id="$2"
  cd "$INSTALL_DIR"
  cat > .env << EOF
BOT_TOKEN=$token
ADMIN_USER_ID=$admin_id
PING_DEFAULT_INTERVAL=0.2
PING_DEFAULT_COUNT=10
EOF
  echo ".env written."
}

# Create systemd user service
install_systemd() {
  mkdir -p "$HOME/.config/systemd/user"
  local unit="$HOME/.config/systemd/user/${SERVICE_NAME}.service"
  cat > "$unit" << EOF
[Unit]
Description=Ping Status
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python -m src.main
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
  echo "Systemd user unit: $unit"
}

# Stop service
stop_service() {
  systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
}

# Start service
start_service() {
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable "$SERVICE_NAME" 2>/dev/null || true
  systemctl --user start "$SERVICE_NAME"
  echo "Service started. Check: systemctl --user status $SERVICE_NAME"
}

# Option 1: Install
do_install() {
  if [ -d "$INSTALL_DIR/venv" ] && [ -f "$INSTALL_DIR/.env" ]; then
    echo "Already installed at $INSTALL_DIR. Use Update (3) or Fresh install (2)."
    return
  fi
  install_system_deps
  ensure_app
  install_python_deps
  local token
  local admin_id
  token=$(read_token)
  admin_id=$(read_admin_id)
  write_env "$token" "$admin_id"
  install_systemd
  start_service
  echo "Install complete. App: $INSTALL_DIR"
}

# Option 2: Fresh install
do_fresh() {
  stop_service
  if [ -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env" "$INSTALL_DIR/.env.bak"
  fi
  rm -rf "$INSTALL_DIR/venv" "$INSTALL_DIR/.env" "$INSTALL_DIR/jobs.json" 2>/dev/null || true
  if ! (cd "$INSTALL_DIR" 2>/dev/null && in_repo); then
    rm -rf "$INSTALL_DIR/src" "$INSTALL_DIR/requirements.txt" "$INSTALL_DIR/install.sh" "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.gitignore" "$INSTALL_DIR/README.md" 2>/dev/null || true
  fi
  install_system_deps
  ensure_app
  install_python_deps
  local token
  local admin_id
  token=$(read_token)
  admin_id=$(read_admin_id)
  write_env "$token" "$admin_id"
  install_systemd
  start_service
  echo "Fresh install complete. App: $INSTALL_DIR"
}

# Option 3: Update
do_update() {
  install_system_deps
  cd "$INSTALL_DIR"
  if [ -d ".git" ]; then
    git fetch origin "$REPO_BRANCH"
    git checkout "$REPO_BRANCH"
    git pull origin "$REPO_BRANCH" || true
  else
    ensure_app
  fi
  install_python_deps
  stop_service
  start_service
  echo "Update complete."
}

# Option 4: Complete uninstall
do_uninstall() {
  stop_service
  rm -f "$HOME/.config/systemd/user/${SERVICE_NAME}.service"
  systemctl --user daemon-reload 2>/dev/null || true
  rm -rf "$INSTALL_DIR"
  echo "Uninstall complete. $INSTALL_DIR removed."
}

# Main menu
main() {
  if in_repo; then
    INSTALL_DIR=$(cd "$(dirname "$0")" && pwd)
    cd "$INSTALL_DIR"
  fi

  echo "Ping Status"
  echo "Install dir: $INSTALL_DIR"
  echo ""
  echo "1) Install      - First-time install"
  echo "2) Fresh install - Reinstall from scratch"
  echo "3) Update       - Pull latest code, keep .env and jobs"
  echo "4) Uninstall    - Remove app and service"
  echo ""
  read -rp "Choice [1-4]: " choice

  case "$choice" in
    1) do_install ;;
    2) do_fresh ;;
    3) do_update ;;
    4) do_uninstall ;;
    *) echo "Invalid choice."; exit 1 ;;
  esac
}

main "$@"
