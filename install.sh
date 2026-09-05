#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
#  P2P Merchant Price Bot — One-Click VPS Installer
#  Ubuntu 20.04 / 22.04 / 24.04 — run as root or regular user with sudo
#
#  Usage:
#    curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh | bash
#    curl -fsSL .../install.sh | bash -s -- --token 123:ABC --admins 123456 --asset USDT --fiat USD
#    git clone https://github.com/sarakmacbook/exchange.git && cd exchange && sudo bash install.sh
#    sudo bash install.sh --token 123:ABC --admins 123456,789012
#    sudo bash install.sh --reconfigure   # re-run wizard
#    sudo bash install.sh --update        # pull + restart
#    sudo bash install.sh --uninstall     # remove service
# ─────────────────────────────────────────────────────────────

REPO_URL="https://github.com/sarakmacbook/exchange.git"
RAW_URL="https://raw.githubusercontent.com/sarakmacbook/exchange/main"
DEFAULT_DIR="$HOME/exchange"
if [[ $EUID -eq 0 ]]; then DEFAULT_DIR="/opt/p2p-bot"; fi

INSTALL_DIR="$DEFAULT_DIR"
SERVICE_NAME="p2p-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# CLI overrides (also read from ENV: BOT_TOKEN, ADMIN_IDS, ASSET, FIAT, INTERVAL)
ARG_TOKEN="${BOT_TOKEN:-}"
ARG_ADMINS="${ADMIN_IDS:-}"
ARG_ASSET="${ASSET:-}"
ARG_FIAT="${FIAT:-}"
ARG_INTERVAL="${INTERVAL:-}"
RECONFIGURE=0
DO_UPDATE=0
DO_UNINSTALL=0
NON_INTERACTIVE=0

# ── colours ──
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
else
  GREEN=''; YELLOW=''; RED=''; CYAN=''; BOLD=''; DIM=''; NC=''
fi
info()  { echo -e "${CYAN}ℹ️  $*${NC}"; }
ok()    { echo -e "${GREEN}✅ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $*${NC}"; }
err()   { echo -e "${RED}❌ $*${NC}" >&2; }
step()  { echo -e "\n${BOLD}━━ $* ━━${NC}"; }

usage() {
  cat <<EOF
${BOLD}P2P Bot — One-Click Installer${NC}
Usage: bash install.sh [OPTIONS]

Options:
  --dir PATH              Install directory (default: $DEFAULT_DIR)
  --token TOKEN           Bot token from @BotFather (else prompted)
  --admins IDS            Telegram user ID(s) comma-separated (else prompted)
  --asset SYMBOL          Asset, e.g. USDT (default: USDT)
  --fiat CODE             Fiat,  e.g. USD  (default: USD)
  --interval SEC          Check interval seconds (default: 60)
  --reconfigure           Re-run setup even if config.json exists
  --update                Pull latest code & restart service
  --uninstall             Remove service & keep data
  --help                  Show this help

Env alternatives: BOT_TOKEN, ADMIN_IDS, ASSET, FIAT, INTERVAL

Examples:
  curl -fsSL $RAW_URL/install.sh | bash
  curl -fsSL $RAW_URL/install.sh | bash -s -- --token 123:ABC --admins 123456
  sudo bash install.sh --dir /opt/p2p-bot --asset BTC --fiat EUR
EOF
}

# ── arg parse ──
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)        INSTALL_DIR="$2"; shift 2;;
    --token)      ARG_TOKEN="$2"; shift 2;;
    --admins)     ARG_ADMINS="$2"; shift 2;;
    --asset)      ARG_ASSET="$2"; shift 2;;
    --fiat)       ARG_FIAT="$2"; shift 2;;
    --interval)   ARG_INTERVAL="$2"; shift 2;;
    --reconfigure) RECONFIGURE=1; shift;;
    --update)     DO_UPDATE=1; shift;;
    --uninstall)  DO_UNINSTALL=1; shift;;
    --non-interactive) NON_INTERACTIVE=1; shift;;
    --help|-h)    usage; exit 0;;
    --) shift; break;;
    *) err "Unknown option: $1"; usage; exit 1;;
  esac
done

# Handle uninstall early
if [[ $DO_UNINSTALL -eq 1 ]]; then
  exec bash "$(dirname "$0")/uninstall.sh" 2>/dev/null || {
    echo "Uninstalling $SERVICE_NAME ..."
    if systemctl list-units --type=service 2>/dev/null | grep -q "$SERVICE_NAME"; then
      sudo systemctl stop "$SERVICE_NAME" || true
      sudo systemctl disable "$SERVICE_NAME" || true
      sudo rm -f "$SERVICE_FILE"
      sudo systemctl daemon-reload || true
      ok "Service removed."
    else
      warn "Service not found."
    fi
    echo "Data kept in $INSTALL_DIR (remove manually if wanted: rm -rf $INSTALL_DIR)"
    exit 0
  }
fi

# ── helpers ──
have_sudo() { [[ $EUID -eq 0 ]] || sudo -n true 2>/dev/null || sudo -v 2>/dev/null; }
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

need_cmd() { command -v "$1" >/dev/null 2>&1; }

is_systemd() {
  need_cmd systemctl && [[ -d /run/systemd/system ]] && [[ "$(ps -p 1 -o comm= 2>/dev/null || echo init)" == "systemd" ]]
}

# Detect if we're running via  curl | bash  (no local repo)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd || echo ".")"
HAS_LOCAL_REPO=0
if [[ -f "$SCRIPT_DIR/bot.py" && -f "$SCRIPT_DIR/requirements.txt" ]]; then
  HAS_LOCAL_REPO=1
fi

banner() {
cat <<'BANNER'
 ____  ____  ____      ____        _
|  _ \|  _ \|  _ \    | __ )  ___ | |_
| |_) | |_) | |_) |   |  _ \ / _ \| __|
|  __/|  __/|  __/    | |_) | (_) | |_
|_|   |_|   |_|       |____/ \___/ \__|
  P2P Merchant Price Bot — One-Click VPS Installer
BANNER
echo -e "${DIM}Ubuntu 20.04 / 22.04 / 24.04 · Binance · Bybit · OKX · Bitget${NC}\n"
}

# ── 1. banner & checks ──
banner

if [[ $DO_UPDATE -eq 1 ]]; then
  info "Update mode — will pull latest code and restart."
fi

step "1/6  Checking system"
if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  echo "  OS: $PRETTY_NAME  ($VERSION_ID)  arch: $(uname -m)"
  if [[ "${ID:-}" != "ubuntu" && "${ID:-}" != "debian" ]]; then
    warn "Not Ubuntu/Debian ($ID) — will try to install anyway."
  fi
else
  warn "/etc/os-release not found — continuing anyway."
fi

if ! have_sudo && [[ $EUID -ne 0 ]]; then
  err "This installer needs sudo for apt + systemd."
  echo "  Run:  sudo bash install.sh"
  echo "  Or:   su -c 'bash install.sh'"
  exit 1
fi

if ! is_systemd; then
  warn "systemd not detected — will use nohup fallback (no auto-restart on reboot)."
  warn "For production, use a VPS with systemd (most Ubuntu VPS have it)."
fi

# ── 2. system deps ──
step "2/6  Installing system packages"
export DEBIAN_FRONTEND=noninteractive
if [[ -n "${SKIP_APT:-}" ]]; then
  info "SKIP_APT set — skipping apt update/install"
else
  $SUDO apt-get update -y || warn "apt update failed — continuing anyway (may need manual: sudo apt update)"
  $SUDO apt-get install -y python3 python3-pip python3-venv git curl ca-certificates || warn "apt install failed — continuing; ensure python3/venv/git are installed"
fi

# ensure python is 3.8+ (Ubuntu 20.04 has 3.8 — still works)
PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "  Python: $PY_VER  ($(python3 --version))"
if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3,8) else 1)'; then
  err "Python $PY_VER too old — need 3.8+. Please upgrade Ubuntu."
  exit 1
fi

# ── 3. get / update source ──
step "3/6  Getting bot source"

# Resolve install dir — if has local repo and no --dir override, use script dir
if [[ $HAS_LOCAL_REPO -eq 1 && "$INSTALL_DIR" == "$DEFAULT_DIR" ]]; then
  # if script dir looks like a real install dir, prefer it
  if [[ "$SCRIPT_DIR" != "." && "$SCRIPT_DIR" != "/tmp" ]]; then
    INSTALL_DIR="$SCRIPT_DIR"
  fi
fi

echo "  Install dir: $INSTALL_DIR"

if [[ -d "$INSTALL_DIR/.git" ]]; then
  info "Existing repo found — pulling latest..."
  git -C "$INSTALL_DIR" pull --ff-only || warn "git pull failed — continuing with existing files."
elif [[ -d "$INSTALL_DIR" && -f "$INSTALL_DIR/bot.py" ]]; then
  info "Existing install dir without git — keeping files."
elif [[ ! -d "$INSTALL_DIR" ]]; then
  if [[ $HAS_LOCAL_REPO -eq 1 && "$SCRIPT_DIR" != "$INSTALL_DIR" ]]; then
    info "Copying local files to $INSTALL_DIR ..."
    mkdir -p "$INSTALL_DIR"
    cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR"/ 2>/dev/null || true
    cp -r "$SCRIPT_DIR"/.git "$INSTALL_DIR"/ 2>/dev/null || true
  else
    info "Cloning $REPO_URL → $INSTALL_DIR ..."
    git clone "$REPO_URL" "$INSTALL_DIR" || {
      # fallback: if git fails (e.g. rate limit), create dir and download raw files
      warn "git clone failed — downloading files directly..."
      mkdir -p "$INSTALL_DIR"
      curl -fsSL "$RAW_URL/bot.py" -o "$INSTALL_DIR/bot.py"
      curl -fsSL "$RAW_URL/exchanges.py" -o "$INSTALL_DIR/exchanges.py"
      curl -fsSL "$RAW_URL/requirements.txt" -o "$INSTALL_DIR/requirements.txt"
    }
  fi
else
  # dir exists but empty
  if [[ $HAS_LOCAL_REPO -eq 1 ]]; then
    cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR"/ 2>/dev/null || true
  else
    git clone "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || true
  fi
fi

cd "$INSTALL_DIR"
echo "  Files: $(ls -1 bot.py exchanges.py requirements.txt 2>/dev/null | tr '\n' ' ')"

# ── 4. venv & deps ──
step "4/6  Setting up Python environment"
if [[ ! -d "$INSTALL_DIR/venv" ]]; then
  python3 -m venv "$INSTALL_DIR/venv"
  ok "Created venv at $INSTALL_DIR/venv"
else
  info "venv already exists — reusing."
fi
# shellcheck disable=SC1091
source "$INSTALL_DIR/venv/bin/activate"
pip install --upgrade pip -q
pip install -r requirements.txt -q
ok "Dependencies installed ($(pip freeze | wc -l) packages)"

# ── 5. config ──
step "5/6  Configuring bot"

CONFIG_FILE="$INSTALL_DIR/config.json"
NEED_SETUP=0
if [[ ! -f "$CONFIG_FILE" ]]; then NEED_SETUP=1; fi
if [[ $RECONFIGURE -eq 1 ]]; then NEED_SETUP=1; fi
if [[ $DO_UPDATE -eq 1 ]]; then NEED_SETUP=0; fi # don't prompt on --update

# Helper: validate token looks plausible
valid_token() { [[ "$1" == *":"* && ${#1} -gt 20 ]]; }
valid_admins() { [[ "$1" =~ ^[0-9,\ ]+$ ]]; }

# Non-interactive fast path: if args/env provided, write config directly
try_write_from_args() {
  local tok="${ARG_TOKEN:-}" admins="${ARG_ADMINS:-}" asset="${ARG_ASSET:-USDT}" fiat="${ARG_FIAT:-USD}" interval="${ARG_INTERVAL:-60}"
  # fall back to existing config values if reconfigure but arg not given? No, require both.
  if [[ -n "$tok" && -n "$admins" ]]; then
    if ! valid_token "$tok"; then err "Token looks invalid (should contain ':' and be longer)."; return 1; fi
    if ! valid_admins "$admins"; then err "Admins should be comma-separated numeric IDs."; return 1; fi
    asset="${asset^^}"; fiat="${fiat^^}"
    interval="${interval//[^0-9]/}"; [[ -z "$interval" ]] && interval=60
    # strip spaces from admins
    admins="$(echo "$admins" | tr -d ' ')"
    cat > "$CONFIG_FILE" <<EOF
{
 "token": "$tok",
 "admins": "$admins",
 "asset": "$asset",
 "fiat": "$fiat",
 "interval": $interval
}
EOF
    chmod 600 "$CONFIG_FILE"
    ok "Config written from CLI/env → $CONFIG_FILE"
    echo "  asset=$asset fiat=$fiat interval=${interval}s admins=$admins"
    return 0
  fi
  return 1
}

# Ask helper for interactive mode
ask() {
  local prompt="$1" default="${2:-}" var
  if [[ -n "$default" ]]; then prompt="$prompt [$default]"; fi
  prompt="$prompt: "
  read -r -p "$prompt" var || true
  var="${var:-$default}"
  echo "$var"
}

if [[ $NEED_SETUP -eq 1 ]]; then
  # try non-interactive first
  if try_write_from_args; then
    :
  elif [[ ! -t 0 || $NON_INTERACTIVE -eq 1 ]]; then
    err "config.json not found and no --token/--admins provided in non-interactive mode."
    echo ""
    echo "  Provide them via flags or env:"
    echo "    curl -fsSL $RAW_URL/install.sh | bash -s -- --token 123:ABC --admins 123456"
    echo "    BOT_TOKEN=123:ABC ADMIN_IDS=123456 bash install.sh"
    echo ""
    echo "  Or run interactively on the VPS:"
    echo "    bash install.sh"
    echo "    sudo bash install.sh --reconfigure"
    exit 1
  else
    # interactive wizard
    echo ""
    echo -e "${BOLD}🤖 First-time setup — you will be asked 5 questions${NC}"
    echo -e "${DIM}  Get bot token from @BotFather on Telegram → /newbot${NC}"
    echo -e "${DIM}  Get your user ID from @userinfobot on Telegram${NC}"
    echo ""
    while true; do
      TOK_INPUT="$(ask "Bot token from @BotFather" "${ARG_TOKEN:-}")"
      if valid_token "$TOK_INPUT"; then ARG_TOKEN="$TOK_INPUT"; break; else echo -e "${RED}  ❌ Token should look like 123456:ABC... — try again${NC}"; fi
    done
    while true; do
      ADM_INPUT="$(ask "Your Telegram user ID(s), comma-separated" "${ARG_ADMINS:-}")"
      if valid_admins "$ADM_INPUT"; then ARG_ADMINS="$ADM_INPUT"; break; else echo -e "${RED}  ❌ Should be numbers like 123456 or 123,456${NC}"; fi
    done
    ARG_ASSET="$(ask "Asset" "${ARG_ASSET:-USDT}")"; ARG_ASSET="${ARG_ASSET^^}"; [[ -z "$ARG_ASSET" ]] && ARG_ASSET="USDT"
    ARG_FIAT="$(ask "Fiat currency" "${ARG_FIAT:-USD}")"; ARG_FIAT="${ARG_FIAT^^}"; [[ -z "$ARG_FIAT" ]] && ARG_FIAT="USD"
    ARG_INTERVAL="$(ask "Check prices every N seconds" "${ARG_INTERVAL:-60}")"; ARG_INTERVAL="${ARG_INTERVAL//[^0-9]/}"; [[ -z "$ARG_INTERVAL" ]] && ARG_INTERVAL=60

    ARG_ADMINS="$(echo "$ARG_ADMINS" | tr -d ' ')"
    cat > "$CONFIG_FILE" <<EOF
{
 "token": "$ARG_TOKEN",
 "admins": "$ARG_ADMINS",
 "asset": "$ARG_ASSET",
 "fiat": "$ARG_FIAT",
 "interval": $ARG_INTERVAL
}
EOF
    chmod 600 "$CONFIG_FILE"
    ok "Saved to $CONFIG_FILE"
  fi
else
  ok "Config exists — keeping $CONFIG_FILE (use --reconfigure to change)"
  cat "$CONFIG_FILE" | python3 -m json.tool 2>/dev/null | sed 's/"token": ".*"/"token": "***"/' || cat "$CONFIG_FILE"
fi

# ensure data.json exists
if [[ ! -f "$INSTALL_DIR/data.json" ]]; then
  echo '{"group": null, "auto": false, "merchants": {}, "last": {}}' > "$INSTALL_DIR/data.json"
fi
chmod 600 "$CONFIG_FILE" 2>/dev/null || true
chmod 600 "$INSTALL_DIR/data.json" 2>/dev/null || true

# chown to correct user if installed as root to /opt
if [[ $EUID -eq 0 && -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  chown -R "$SUDO_USER:$SUDO_USER" "$INSTALL_DIR" 2>/dev/null || true
  REAL_USER="$SUDO_USER"
  REAL_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
else
  REAL_USER="$(whoami)"
  REAL_HOME="$HOME"
fi
# if install dir is /opt/p2p-bot but user is ubuntu, keep ownership to that user
if [[ "$INSTALL_DIR" == "/opt/p2p-bot" ]]; then
  # determine owner: SUDO_USER or current
  OWNER="${SUDO_USER:-$(whoami)}"
  $SUDO chown -R "$OWNER:$OWNER" "$INSTALL_DIR" 2>/dev/null || true
  REAL_USER="$OWNER"
fi

# ── 6. systemd service ──
step "6/6  Installing service"

if is_systemd; then
  echo "  Creating $SERVICE_FILE ..."
  # detect python binary
  PYBIN="$INSTALL_DIR/venv/bin/python"
  if [[ ! -x "$PYBIN" ]]; then PYBIN="$(command -v python3)"; fi

  $SUDO tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=P2P Merchant Price Bot — Binance/Bybit/OKX/Bitget
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYBIN $INSTALL_DIR/bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
# Optional: load env file if you prefer env vars over config.json
# EnvironmentFile=-$INSTALL_DIR/.env
StandardOutput=journal
StandardError=journal
SyslogIdentifier=p2p-bot

# Hardening (uncomment if needed — keep permissive for VPS simplicity)
# NoNewPrivileges=yes
# PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

  $SUDO systemctl daemon-reload
  $SUDO systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true

  # restart or start
  if $SUDO systemctl is-active --quiet "$SERVICE_NAME"; then
    info "Restarting $SERVICE_NAME ..."
    $SUDO systemctl restart "$SERVICE_NAME"
  else
    info "Starting $SERVICE_NAME ..."
    $SUDO systemctl start "$SERVICE_NAME"
  fi

  sleep 3
  if $SUDO systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Service is running (systemd)"
  else
    # Check if it's restarting (RestartSec=5 → might be inactive briefly)
    sleep 2
    if $SUDO systemctl is-active --quiet "$SERVICE_NAME"; then
      ok "Service is running (systemd) — after restart delay"
    else
      warn "Service not active yet — check logs (token/network?):"
      $SUDO journalctl -u "$SERVICE_NAME" -n 40 --no-pager 2>/dev/null | tail -n 40 || $SUDO systemctl status "$SERVICE_NAME" --no-pager 2>/dev/null | tail -n 40 || true
      echo ""
      warn "Bot is installed and will keep retrying (Restart=always)."
      warn "Check: sudo journalctl -u $SERVICE_NAME -f"
      warn "Or run manually: $INSTALL_DIR/venv/bin/python $INSTALL_DIR/bot.py"
      warn "Common causes: invalid token, no internet, or Telegram blocked"
      # don't exit 1 — let install succeed so user can fix token and restart
    fi
  fi

else
  # fallback: nohup
  warn "systemd unavailable — starting with nohup fallback..."
  PYBIN="$INSTALL_DIR/venv/bin/python"
  # kill old
  pkill -f "$INSTALL_DIR/bot.py" 2>/dev/null || true
  nohup "$PYBIN" "$INSTALL_DIR/bot.py" > "$INSTALL_DIR/bot.log" 2>&1 &
  echo $! > "$INSTALL_DIR/bot.pid"
  # add @reboot cron
  (crontab -l 2>/dev/null | grep -v "$INSTALL_DIR/bot.py"; echo "@reboot $PYBIN $INSTALL_DIR/bot.py >> $INSTALL_DIR/bot.log 2>&1") | crontab -
  ok "Started via nohup (PID $(cat "$INSTALL_DIR/bot.pid")) — logs: $INSTALL_DIR/bot.log"
  info "Reboot persistence via cron @reboot"
fi

# ── done ──
echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  🎉 Installed! Bot is running.${NC}"
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}Install dir:${NC} $INSTALL_DIR"
echo -e "  ${BOLD}Service:${NC}     $SERVICE_NAME  (systemctl)"
echo -e "  ${BOLD}Config:${NC}      $CONFIG_FILE"
echo -e "  ${BOLD}Data:${NC}        $INSTALL_DIR/data.json"
echo ""
echo -e "  ${BOLD}Next steps on Telegram:${NC}"
echo -e "   1. Open your bot → send ${CYAN}/start${NC} (in private chat)"
echo -e "   2. Add bot to your group → send ${CYAN}/setgroup${NC} inside the group"
echo -e "   3. Back in private chat → ${CYAN}paste a merchant URL${NC} to add it"
echo -e "      Binance / Bybit / OKX / Bitget public merchant links supported"
echo -e "   4. Use panel buttons: ${CYAN}📊 Post now${NC} · ${CYAN}🟢 Auto ON/OFF${NC} · ${CYAN}📋 Merchants${NC}"
echo ""
echo -e "  ${BOLD}Useful commands:${NC}"
if is_systemd; then
echo -e "   ${DIM}sudo systemctl status $SERVICE_NAME${NC}     — check status"
echo -e "   ${DIM}sudo journalctl -u $SERVICE_NAME -f${NC}      — live logs"
echo -e "   ${DIM}sudo systemctl restart $SERVICE_NAME${NC}     — restart"
echo -e "   ${DIM}sudo systemctl stop $SERVICE_NAME${NC}        — stop"
fi
echo -e "   ${DIM}sudo bash $INSTALL_DIR/install.sh --reconfigure${NC}  — change token/pair"
echo -e "   ${DIM}sudo bash $INSTALL_DIR/install.sh --update${NC}       — update to latest"
echo -e "   ${DIM}sudo bash $INSTALL_DIR/install.sh --uninstall${NC}    — remove service"
echo ""
if is_systemd; then
  echo -e "${DIM}── last 15 log lines ──${NC}"
  $SUDO journalctl -u "$SERVICE_NAME" -n 15 --no-pager 2>/dev/null | tail -n 15 || cat "$INSTALL_DIR/bot.log" 2>/dev/null | tail -n 15 || true
fi
echo ""
