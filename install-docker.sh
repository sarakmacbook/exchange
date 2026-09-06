#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
#  P2P Merchant Price Bot — One-Click Docker Installer
#  Ubuntu / Debian / macOS / any machine with Docker
#
#  Usage:
#    curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install-docker.sh | bash -s -- --token 123:ABC --admins 123456
#    git clone https://github.com/sarakmacbook/exchange.git && cd exchange && bash install-docker.sh
#    bash install-docker.sh --token 123:ABC --admins 123456,789012 --asset USDT --fiat USD
#    bash install-docker.sh --reconfigure   # re-run setup wizard
#    bash install-docker.sh --update        # pull + rebuild + restart
#    bash install-docker.sh --down          # stop container (keep data)
# ─────────────────────────────────────────────────────────────

REPO_URL="https://github.com/sarakmacbook/exchange.git"
RAW_URL="https://raw.githubusercontent.com/sarakmacbook/exchange/main"
DEFAULT_DIR="$HOME/exchange"
COMPOSE_FILE="docker-compose.yml"

INSTALL_DIR="$DEFAULT_DIR"
CONTAINER_NAME="p2p-bot"

# CLI overrides (also read from ENV: BOT_TOKEN, ADMIN_IDS, ASSET, FIAT, INTERVAL)
ARG_TOKEN="${BOT_TOKEN:-}"
ARG_ADMINS="${ADMIN_IDS:-}"
ARG_ASSET="${ASSET:-}"
ARG_FIAT="${FIAT:-}"
ARG_INTERVAL="${INTERVAL:-}"
RECONFIGURE=0
DO_UPDATE=0
DO_DOWN=0
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
${BOLD}P2P Bot — One-Click Docker Installer${NC}
Usage: bash install-docker.sh [OPTIONS]

Options:
  --dir PATH              Install/clone directory (default: $DEFAULT_DIR)
  --token TOKEN           Bot token from @BotFather (else prompted)
  --admins IDS            Telegram user ID(s) comma-separated (else prompted)
  --asset SYMBOL          Asset, e.g. USDT (default: USDT)
  --fiat CODE             Fiat,  e.g. USD  (default: USD)
  --interval SEC          Check interval seconds (default: 60)
  --reconfigure           Re-run setup even if config.json exists
  --update                Pull latest code, rebuild image & restart
  --down                  Stop & remove the container (keep config/data)
  --non-interactive       Never prompt (fail if no --token/--admins)
  --help                  Show this help

Env alternatives: BOT_TOKEN, ADMIN_IDS, ASSET, FIAT, INTERVAL

Examples:
  bash install-docker.sh --token 123:ABC --admins 123456
  bash install-docker.sh --asset BTC --fiat EUR --interval 30
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
    --down)       DO_DOWN=1; shift;;
    --non-interactive) NON_INTERACTIVE=1; shift;;
    --help|-h)    usage; exit 0;;
    --) shift; break;;
    *) err "Unknown option: $1"; usage; exit 1;;
  esac
done

# ── helpers ──
need_cmd() { command -v "$1" >/dev/null 2>&1; }
have_sudo() { [[ $EUID -eq 0 ]] || sudo -n true 2>/dev/null || sudo -v 2>/dev/null; }
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

# Detect if we're running from a local repo checkout
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd || echo ".")"
HAS_LOCAL_REPO=0
if [[ -f "$SCRIPT_DIR/bot.py" && -f "$SCRIPT_DIR/$COMPOSE_FILE" ]]; then
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
  P2P Merchant Price Bot — One-Click Docker Installer
BANNER
echo -e "${DIM}Binance · Bybit · OKX · Bitget — Docker Compose${NC}\n"
}

banner

# ── 1. checks ──
step "1/5  Checking system"
if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  echo "  OS: $PRETTY_NAME  arch: $(uname -m)"
elif [[ "$(uname -s)" == "Darwin" ]]; then
  echo "  OS: macOS  arch: $(uname -m)"
else
  warn "Unknown OS — continuing anyway."
fi

# ── 2. docker ──
step "2/5  Checking Docker"
COMPOSE_BIN=()
if need_cmd docker; then
  echo "  docker: $(docker --version 2>/dev/null || echo found)"
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_BIN=(docker compose)
    echo "  compose: $(docker compose version 2>/dev/null)"
  elif need_cmd docker-compose; then
    COMPOSE_BIN=(docker-compose)
    echo "  compose: $(docker-compose --version 2>/dev/null)"
  fi
fi

if [[ ${#COMPOSE_BIN[@]} -eq 0 ]]; then
  if [[ -n "${SKIP_DOCKER_INSTALL:-}" ]]; then
    err "Docker / compose not found and SKIP_DOCKER_INSTALL is set."
    exit 1
  fi
  if [[ "$(uname -s)" == "Linux" && -n "${ID:-}" && "${ID:-}" =~ ^(ubuntu|debian)$ ]]; then
    warn "Docker not installed — installing via apt (needs sudo)..."
    if ! have_sudo; then err "sudo required to install Docker."; exit 1; fi
    export DEBIAN_FRONTEND=noninteractive
    $SUDO apt-get update -y || true
    $SUDO apt-get install -y docker.io docker-compose-plugin 2>/dev/null \
      || $SUDO apt-get install -y docker.io docker-compose || {
        err "Could not install docker/compose via apt — install manually, then re-run."
        exit 1
      }
    $SUDO systemctl enable --now docker 2>/dev/null || $SUDO service docker start 2>/dev/null || true
    if need_cmd docker && docker compose version >/dev/null 2>&1; then
      COMPOSE_BIN=(docker compose)
    elif need_cmd docker-compose; then
      COMPOSE_BIN=(docker-compose)
    else
      err "Docker installed but compose is still missing. Install 'docker-compose-plugin' or Docker Desktop, then re-run."
      exit 1
    fi
  else
    err "Docker not found. Please install Docker first:"
    echo "    Ubuntu/Debian:  sudo apt-get install docker.io docker-compose-plugin"
    echo "    macOS:          https://docs.docker.com/desktop/setup/install/mac-install/"
    echo "    Other:          https://docs.docker.com/engine/install/"
    exit 1
  fi
fi

if ! docker info >/dev/null 2>&1; then
  warn "Docker daemon not reachable — trying to start it..."
  if [[ "$(uname -s)" == "Linux" ]]; then
    $SUDO systemctl start docker 2>/dev/null || $SUDO service docker start 2>/dev/null || true
    sleep 2
  fi
  if ! docker info >/dev/null 2>&1; then
    err "Docker daemon is not running. Start it (Docker Desktop on macOS) and re-run."
    exit 1
  fi
fi
ok "Docker ready"

# ── 3. get source ──
step "3/5  Getting bot source"
if [[ $HAS_LOCAL_REPO -eq 1 && "$INSTALL_DIR" == "$DEFAULT_DIR" && "$SCRIPT_DIR" != "." && "$SCRIPT_DIR" != "/tmp" ]]; then
  INSTALL_DIR="$SCRIPT_DIR"
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
    git clone "$REPO_URL" "$INSTALL_DIR" || { err "git clone failed."; exit 1; }
  fi
else
  if [[ $HAS_LOCAL_REPO -eq 1 ]]; then
    cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR"/ 2>/dev/null || true
  else
    git clone "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || { err "git clone failed."; exit 1; }
  fi
fi
cd "$INSTALL_DIR"

# ── 4. config / .env ──
step "4/5  Configuring bot"

CONFIG_FILE="$INSTALL_DIR/config.json"
ENV_FILE="$INSTALL_DIR/.env"
DATA_FILE="$INSTALL_DIR/data.json"
NEED_SETUP=0
if [[ ! -f "$CONFIG_FILE" ]]; then NEED_SETUP=1; fi
if [[ $RECONFIGURE -eq 1 ]]; then NEED_SETUP=1; fi
if [[ $DO_UPDATE -eq 1 ]]; then NEED_SETUP=0; fi

valid_token() { [[ "$1" == *":"* && ${#1} -gt 20 ]]; }
valid_admins() { [[ "$1" =~ ^[0-9,\ ]+$ ]]; }

# Non-interactive fast path: write config.json + .env from args/env
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

    cat > "$ENV_FILE" <<EOF
# Generated by install-docker.sh — secrets, keep private
BOT_TOKEN=$tok
ADMIN_IDS=$admins
ASSET=$asset
FIAT=$fiat
INTERVAL=$interval
EOF
    chmod 600 "$ENV_FILE"
    ok "Config written → $CONFIG_FILE + $ENV_FILE"
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

# If .env exists but config.json missing (e.g. after fresh clone), reuse env values
if [[ ! -f "$CONFIG_FILE" && -f "$ENV_FILE" ]]; then
  ARG_TOKEN="$(grep -E '^BOT_TOKEN=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
  ARG_ADMINS="$(grep -E '^ADMIN_IDS=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
  ARG_ASSET="$(grep -E '^ASSET=' "$ENV_FILE"  | tail -1 | cut -d= -f2- || true)"
  ARG_FIAT="$(grep -E '^FIAT=' "$ENV_FILE"    | tail -1 | cut -d= -f2- || true)"
  ARG_INTERVAL="$(grep -E '^INTERVAL=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
fi

if [[ $NEED_SETUP -eq 1 ]]; then
  if write_config; then
    :
  elif [[ ! -t 0 || $NON_INTERACTIVE -eq 1 ]]; then
    err "config.json not found and no --token/--admins provided in non-interactive mode."
    echo ""
    echo "  Provide them via flags or env:"
    echo "    bash install-docker.sh --token 123:ABC --admins 123456"
    echo "    BOT_TOKEN=123:ABC ADMIN_IDS=123456 bash install-docker.sh"
    echo ""
    echo "  Or run interactively:  bash install-docker.sh"
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
  # make sure .env exists next to config.json for docker compose
  if [[ ! -f "$ENV_FILE" ]]; then
    info "Generating .env from config.json ..."
    {
      echo "# Generated by install-docker.sh — secrets, keep private"
      echo "BOT_TOKEN=$(python3 -c "import json;print(json.load(open('$CONFIG_FILE'))['token'])" 2>/dev/null || echo "PLACEHOLDER")"
      echo "ADMIN_IDS=$(python3 -c "import json;print(json.load(open('$CONFIG_FILE'))['admins'])" 2>/dev/null || echo "123456789")"
      echo "ASSET=$(python3 -c "import json;print(json.load(open('$CONFIG_FILE'))['asset'])" 2>/dev/null || echo "USDT")"
      echo "FIAT=$(python3 -c "import json;print(json.load(open('$CONFIG_FILE'))['fiat'])" 2>/dev/null || echo "USD")"
      echo "INTERVAL=$(python3 -c "import json;print(json.load(open('$CONFIG_FILE'))['interval'])" 2>/dev/null || echo "60")"
    } > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  fi
fi

# ensure data.json exists (Docker volume mounts need real files)
if [[ ! -f "$DATA_FILE" ]]; then
  echo '{"group": null, "auto": false, "merchants": {}, "last": {}}' > "$DATA_FILE"
fi
chmod 600 "$CONFIG_FILE" 2>/dev/null || true
chmod 600 "$DATA_FILE" 2>/dev/null || true
chmod 600 "$ENV_FILE" 2>/dev/null || true

# ── 5. docker up ──
step "5/5  Starting with ${COMPOSE_BIN[*]}"

if [[ $DO_DOWN -eq 1 ]]; then
  info "Stopping & removing container (keeping config/data)..."
  "${COMPOSE_BIN[@]}" down
  ok "Container removed. Data kept in $INSTALL_DIR"
  echo "  Re-run:   bash install-docker.sh"
  echo "  Wipe all: docker compose down -v && rm -f config.json data.json .env"
  exit 0
fi

if [[ $DO_UPDATE -eq 1 ]]; then
  git -C "$INSTALL_DIR" pull --ff-only 2>/dev/null || warn "git pull skipped/failed — rebuilding anyway."
  info "Rebuilding image ..."
  "${COMPOSE_BIN[@]}" up -d --build --force-recreate
else
  "${COMPOSE_BIN[@]}" up -d --build
fi

sleep 4
echo ""
if "${COMPOSE_BIN[@]}" ps --format 'table {{.Name}}\t{{.Status}}' 2>/dev/null | grep -q "$CONTAINER_NAME"; then
  ok "Container is up"
else
  warn "Container not listed yet — check logs below."
fi

# ── done ──
echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  🎉 Installed! Bot container is running.${NC}"
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}Install dir:${NC} $INSTALL_DIR"
echo -e "  ${BOLD}Container:${NC}   $CONTAINER_NAME  (restart: unless-stopped)"
echo -e "  ${BOLD}Config:${NC}      $CONFIG_FILE + $ENV_FILE"
echo -e "  ${BOLD}Data:${NC}        $DATA_FILE"
echo ""
echo -e "  ${BOLD}Next steps on Telegram:${NC}"
echo -e "   1. Open your bot → send ${CYAN}/start${NC} (in private chat)"
echo -e "   2. Add bot to your group → send ${CYAN}/setgroup${NC} inside the group"
echo -e "   3. Back in private chat → ${CYAN}paste a merchant URL${NC} to add it"
echo -e "   4. Tap ${CYAN}🟢 Auto: ON${NC} — prices post automatically"
echo ""
echo -e "  ${BOLD}Useful commands:${NC}"
echo -e "   ${DIM}${COMPOSE_BIN[*]} ps${NC}               — status"
echo -e "   ${DIM}${COMPOSE_BIN[*]} logs -f${NC}          — live logs"
echo -e "   ${DIM}${COMPOSE_BIN[*]} restart${NC}          — restart"
echo -e "   ${DIM}bash $INSTALL_DIR/install-docker.sh --reconfigure${NC}  — change token/pair"
echo -e "   ${DIM}bash $INSTALL_DIR/install-docker.sh --update${NC}       — update to latest"
echo -e "   ${DIM}bash $INSTALL_DIR/install-docker.sh --down${NC}         — stop container"
echo ""
echo -e "${DIM}── last 20 log lines ──${NC}"
"${COMPOSE_BIN[@]}" logs --tail 20 2>/dev/null || true
echo ""
