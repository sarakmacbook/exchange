#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
#  P2P Merchant Price Bot — One-Click Local Installer
#  Works anywhere: macOS, Windows (WSL/Git Bash), Linux without
#  systemd, shared hosting, laptops. Uses venv + nohup + autostart
#  via launchd (macOS) or cron @reboot (Linux).
#
#  Usage:
#    curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install-local.sh | bash
#    git clone https://github.com/sarakmacbook/exchange.git && cd exchange && bash install-local.sh
#    bash install-local.sh --token 123:ABC --admins 123456 --asset USDT --fiat USD
#    bash install-local.sh --reconfigure    # re-run setup wizard
#    bash install-local.sh --update         # pull + update + restart
#    bash install-local.sh --stop           # stop bot
#    bash install-local.sh --uninstall      # stop + remove autostart (keep data)
# ─────────────────────────────────────────────────────────────

REPO_URL="https://github.com/sarakmacbook/exchange.git"
RAW_URL="https://raw.githubusercontent.com/sarakmacbook/exchange/main"
DEFAULT_DIR="$HOME/exchange-local"

INSTALL_DIR="$DEFAULT_DIR"
BOT_LOG="bot.log"
PID_FILE="bot.pid"

# CLI overrides (also read from ENV: BOT_TOKEN, ADMIN_IDS, ASSET, FIAT, INTERVAL)
ARG_TOKEN="${BOT_TOKEN:-}"
ARG_ADMINS="${ADMIN_IDS:-}"
ARG_ASSET="${ASSET:-}"
ARG_FIAT="${FIAT:-}"
ARG_INTERVAL="${INTERVAL:-}"
RECONFIGURE=0
DO_UPDATE=0
DO_STOP=0
DO_UNINSTALL=0
NO_AUTOSTART=0
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
${BOLD}P2P Bot — One-Click Local Installer (no systemd required)${NC}
Usage: bash install-local.sh [OPTIONS]

Options:
  --dir PATH              Install directory (default: $DEFAULT_DIR)
  --token TOKEN           Bot token from @BotFather (else prompted)
  --admins IDS            Telegram user ID(s) comma-separated (else prompted)
  --asset SYMBOL          Asset, e.g. USDT (default: USDT)
  --fiat CODE             Fiat,  e.g. USD  (default: USD)
  --interval SEC          Check interval seconds (default: 60)
  --reconfigure           Re-run setup even if config.json exists
  --update                Pull latest code, update deps & restart
  --stop                  Stop the bot (keep data & autostart)
  --uninstall             Stop bot & remove autostart (keep data)
  --no-autostart          Install without launchd/cron autostart
  --non-interactive       Never prompt (fail if no --token/--admins)
  --help                  Show this help

Env alternatives: BOT_TOKEN, ADMIN_IDS, ASSET, FIAT, INTERVAL

Examples:
  curl -fsSL $RAW_URL/install-local.sh | bash -s -- --token 123:ABC --admins 123456
  bash install-local.sh --asset BTC --fiat EUR --interval 30
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
    --stop)       DO_STOP=1; shift;;
    --uninstall)  DO_UNINSTALL=1; shift;;
    --no-autostart) NO_AUTOSTART=1; shift;;
    --non-interactive) NON_INTERACTIVE=1; shift;;
    --help|-h)    usage; exit 0;;
    --) shift; break;;
    *) err "Unknown option: $1"; usage; exit 1;;
  esac
done

# ── helpers ──
need_cmd() { command -v "$1" >/dev/null 2>&1; }

# Detect if we're running from a local repo checkout
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd || echo ".")"
HAS_LOCAL_REPO=0
if [[ -f "$SCRIPT_DIR/bot.py" && -f "$SCRIPT_DIR/requirements.txt" ]]; then
  HAS_LOCAL_REPO=1
fi

# Reopen stdin from /dev/tty if piped (curl | bash) so prompts work.
# If there is no controlling TTY, keep stdin as-is (args/env mode).
if [[ ! -t 0 ]]; then
  exec < /dev/tty 2>/dev/null || true
fi

banner() {
cat <<'BANNER'
 ____  ____  ____      ____        _
|  _ \|  _ \|  _ \    | __ )  ___ | |_
| |_) | |_) | |_) |   |  _ \ / _ \| __|
|  __/|  __/|  __/    | |_) | (_) | |_
|_|   |_|   |_|       |____/ \___/ \__|
  P2P Merchant Price Bot — One-Click Local Installer
BANNER
echo -e "${DIM}No systemd needed · macOS / Linux / WSL · venv + nohup${NC}\n"
}

banner

# ── 1. checks ──
step "1/5  Checking system"
if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  echo "  OS: $PRETTY_NAME ($VERSION_ID)  arch: $(uname -m)"
elif [[ "$(uname -s)" == "Darwin" ]]; then
  echo "  OS: macOS  arch: $(uname -m)"
else
  echo "  OS: $(uname -s)  arch: $(uname -m)"
fi

if ! need_cmd python3; then err "python3 not found. Install Python 3.8+ first."; exit 1; fi
if ! need_cmd git; then err "git not found. Install git first."; exit 1; fi
if ! need_cmd curl; then warn "curl not found — will try git clone only."; fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "  Python: $PY_VER  ($(python3 --version))"
if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3,8) else 1)'; then
  err "Python $PY_VER too old — need 3.8+. Please install a newer Python."
  exit 1
fi
if ! python3 -m venv --help >/dev/null 2>&1; then
  warn "python3-venv missing — trying to install it..."
  if [[ "$(uname -s)" == "Linux" ]] && need_cmd apt-get && { [[ $EUID -eq 0 ]] || sudo -n true 2>/dev/null; }; then
    SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"
    export DEBIAN_FRONTEND=noninteractive
    $SUDO apt-get update -y || true
    $SUDO apt-get install -y python3-venv || { err "Could not install python3-venv."; exit 1; }
  else
    err "python3-venv is required. On Debian/Ubuntu: sudo apt-get install python3-venv"
    exit 1
  fi
fi

# ── 2. get source ──
step "2/5  Getting bot source"
# Resolve install dir — if local repo & no --dir override, use script dir
if [[ $HAS_LOCAL_REPO -eq 1 && "$INSTALL_DIR" == "$DEFAULT_DIR" ]]; then
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
      warn "git clone failed — downloading files directly..."
      mkdir -p "$INSTALL_DIR"
      curl -fsSL "$RAW_URL/bot.py" -o "$INSTALL_DIR/bot.py"
      curl -fsSL "$RAW_URL/exchanges.py" -o "$INSTALL_DIR/exchanges.py"
      curl -fsSL "$RAW_URL/requirements.txt" -o "$INSTALL_DIR/requirements.txt"
    }
  fi
else
  if [[ $HAS_LOCAL_REPO -eq 1 ]]; then
    cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR"/ 2>/dev/null || true
  else
    git clone "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || true
  fi
fi
cd "$INSTALL_DIR"
echo "  Files: $(ls -1 bot.py exchanges.py requirements.txt 2>/dev/null | tr '\n' ' ')"

# ── 3. venv & deps ──
step "3/5  Setting up Python environment"
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

# ── 4. config ──
step "4/5  Configuring bot"

CONFIG_FILE="$INSTALL_DIR/config.json"
DATA_FILE="$INSTALL_DIR/data.json"
NEED_SETUP=0
if [[ ! -f "$CONFIG_FILE" ]]; then NEED_SETUP=1; fi
if [[ $RECONFIGURE -eq 1 ]]; then NEED_SETUP=1; fi
if [[ $DO_UPDATE -eq 1 ]]; then NEED_SETUP=0; fi

valid_token() { [[ "$1" == *":"* && ${#1} -gt 20 ]]; }
valid_admins() { [[ "$1" =~ ^[0-9,\ ]+$ ]]; }

write_config() {
  local tok="${ARG_TOKEN:-}" admins="${ARG_ADMINS:-}" asset="${ARG_ASSET:-USDT}" fiat="${ARG_FIAT:-USD}" interval="${ARG_INTERVAL:-60}"
  if [[ -n "$tok" && -n "$admins" ]]; then
    if ! valid_token "$tok"; then err "Token looks invalid (should contain ':' and be longer)."; return 1; fi
    if ! valid_admins "$admins"; then err "Admins should be comma-separated numeric IDs."; return 1; fi
    admins="$(echo "$admins" | tr -d ' ')"
    asset="${asset^^}"; fiat="${fiat^^}"
    interval="${interval//[^0-9]/}"; [[ -z "$interval" ]] && interval=60
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
    ok "Config written → $CONFIG_FILE"
    echo "  asset=$asset fiat=$fiat interval=${interval}s admins=$admins"
    return 0
  fi
  return 1
}

ask() {
  local prompt="$1" default="${2:-}" var
  if [[ -n "$default" ]]; then prompt="$prompt [$default]"; fi
  read -r -p "$prompt: " var || true
  var="${var:-$default}"
  echo "$var"
}

if [[ $NEED_SETUP -eq 1 ]]; then
  if write_config; then
    :
  elif [[ ! -t 0 || $NON_INTERACTIVE -eq 1 ]]; then
    err "config.json not found and no --token/--admins provided in non-interactive mode."
    echo ""
    echo "  Provide them via flags or env:"
    echo "    bash install-local.sh --token 123:ABC --admins 123456"
    echo "    BOT_TOKEN=123:ABC ADMIN_IDS=123456 bash install-local.sh"
    echo ""
    echo "  Or run interactively:  bash install-local.sh"
    exit 1
  else
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
    ARG_ASSET="$(ask "Asset" "${ARG_ASSET:-USDT}")"
    ARG_FIAT="$(ask "Fiat currency" "${ARG_FIAT:-USD}")"
    ARG_INTERVAL="$(ask "Check prices every N seconds" "${ARG_INTERVAL:-60}")"
    write_config || { err "Could not save configuration."; exit 1; }
  fi
else
  ok "Config exists — keeping $CONFIG_FILE (use --reconfigure to change)"
  cat "$CONFIG_FILE" | python3 -m json.tool 2>/dev/null | sed 's/"token": ".*"/"token": "***"/' || cat "$CONFIG_FILE"
fi

# ensure data.json exists
if [[ ! -f "$DATA_FILE" ]]; then
  echo '{"group": null, "auto": false, "merchants": {}, "last": {}}' > "$DATA_FILE"
fi
chmod 600 "$CONFIG_FILE" 2>/dev/null || true
chmod 600 "$DATA_FILE" 2>/dev/null || true

PYBIN="$INSTALL_DIR/venv/bin/python"
[[ -x "$PYBIN" ]] || PYBIN="$(command -v python3)"

# ── 5. start (nohup + autostart) ──
step "5/5  Starting bot"

# stop previous instance first
if [[ -f "$PID_FILE" ]]; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi
pkill -f "$INSTALL_DIR/bot.py" 2>/dev/null || true

if [[ $DO_STOP -eq 1 ]]; then
  ok "Bot stopped (data kept). Start again: bash $INSTALL_DIR/install-local.sh"
  exit 0
fi

if [[ $DO_UNINSTALL -eq 1 ]]; then
  # remove autostart entries
  if [[ "$(uname -s)" == "Darwin" ]]; then
    PLIST="$HOME/Library/LaunchAgents/com.p2p-bot.plist"
    rm -f "$PLIST" 2>/dev/null || true
    launchctl unload "$PLIST" 2>/dev/null || true
    ok "launchd agent removed"
  fi
  if command -v crontab >/dev/null 2>&1; then
    (crontab -l 2>/dev/null | grep -v "$INSTALL_DIR/bot.py" || true) | crontab - 2>/dev/null || true
    ok "cron @reboot entry removed"
  fi
  ok "Bot uninstalled. Data kept in $INSTALL_DIR (delete manually: rm -rf $INSTALL_DIR)"
  exit 0
fi

nohup "$PYBIN" "$INSTALL_DIR/bot.py" >> "$INSTALL_DIR/$BOT_LOG" 2>&1 &
echo $! > "$PID_FILE"
sleep 3

if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  ok "Bot started (PID $(cat "$PID_FILE")) — logs: $INSTALL_DIR/$BOT_LOG"
else
  warn "Bot process exited quickly — last log lines:"
  tail -n 15 "$INSTALL_DIR/$BOT_LOG" 2>/dev/null || true
  warn "Common cause: missing/invalid token or network (Telegram blocked)."
  warn "Fix token:  bash $INSTALL_DIR/install-local.sh --reconfigure"
fi

# autostart
if [[ $NO_AUTOSTART -eq 0 && "$(uname -s)" == "Darwin" ]]; then
  PLIST_DIR="$HOME/Library/LaunchAgents"
  PLIST="$PLIST_DIR/com.p2p-bot.plist"
  mkdir -p "$PLIST_DIR"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.p2p-bot</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYBIN</string>
    <string>$INSTALL_DIR/bot.py</string>
  </array>
  <key>WorkingDirectory</key><string>$INSTALL_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$INSTALL_DIR/$BOT_LOG</string>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/$BOT_LOG</string>
</dict>
</plist>
EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST" 2>/dev/null || true
  ok "launchd autostart installed (com.p2p-bot)"
elif [[ $NO_AUTOSTART -eq 0 ]] && command -v crontab >/dev/null 2>&1; then
  (crontab -l 2>/dev/null | grep -v "$INSTALL_DIR/bot.py"; echo "@reboot $PYBIN $INSTALL_DIR/bot.py >> $INSTALL_DIR/$BOT_LOG 2>&1") | crontab -
  ok "cron @reboot autostart installed"
else
  info "Autostart skipped (--no-autostart or no crontab)."
fi

# ── done ──
echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  🎉 Installed! Bot is running.${NC}"
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}Install dir:${NC} $INSTALL_DIR"
echo -e "  ${BOLD}PID file:${NC}    $PID_FILE"
echo -e "  ${BOLD}Logs:${NC}        $INSTALL_DIR/$BOT_LOG"
echo -e "  ${BOLD}Config:${NC}      $CONFIG_FILE"
echo ""
echo -e "  ${BOLD}Next steps on Telegram:${NC}"
echo -e "   1. Open your bot → send ${CYAN}/start${NC} (in private chat)"
echo -e "   2. Add bot to your group → send ${CYAN}/setgroup${NC} inside the group"
echo -e "   3. Back in private chat → ${CYAN}paste a merchant URL${NC} to add it"
echo -e "   4. Tap ${CYAN}🟢 Auto: ON${NC} — prices post automatically"
echo ""
echo -e "  ${BOLD}Useful commands:${NC}"
echo -e "   ${DIM}tail -f $INSTALL_DIR/$BOT_LOG${NC}         — live logs"
echo -e "   ${DIM}bash $INSTALL_DIR/install-local.sh --stop${NC}        — stop"
echo -e "   ${DIM}bash $INSTALL_DIR/install-local.sh${NC}              — start"
echo -e "   ${DIM}bash $INSTALL_DIR/install-local.sh --reconfigure${NC}  — change token/pair"
echo -e "   ${DIM}bash $INSTALL_DIR/install-local.sh --update${NC}       — update to latest"
echo -e "   ${DIM}bash $INSTALL_DIR/install-local.sh --uninstall${NC}    — remove autostart (keep data)"
echo ""
