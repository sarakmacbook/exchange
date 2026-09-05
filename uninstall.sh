#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="p2p-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

echo -e "${YELLOW}Uninstalling $SERVICE_NAME ...${NC}"

if command -v systemctl >/dev/null 2>&1 && [[ -f "$SERVICE_FILE" ]]; then
  $SUDO systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  $SUDO systemctl disable "$SERVICE_NAME" 2>/dev/null || true
  $SUDO rm -f "$SERVICE_FILE"
  $SUDO systemctl daemon-reload 2>/dev/null || true
  echo -e "${GREEN}✅ systemd service removed${NC}"
else
  echo "No systemd service found."
fi

# kill nohup fallback
if [[ -f "./bot.pid" ]]; then
  kill "$(cat ./bot.pid)" 2>/dev/null || true
  rm -f ./bot.pid
fi
pkill -f "bot.py" 2>/dev/null || true

# remove cron entry
if command -v crontab >/dev/null 2>&1; then
  (crontab -l 2>/dev/null | grep -v "bot.py" || true) | crontab - 2>/dev/null || true
  echo "Cron @reboot entry cleaned (if any)."
fi

echo ""
echo "Data files kept (so you can reinstall without losing merchants):"
echo "  $(pwd)/config.json"
echo "  $(pwd)/data.json"
echo "  $(pwd)/venv"
echo ""
echo "To fully wipe:"
echo "  rm -rf venv config.json data.json bot.log"
echo "  # if installed to /opt/p2p-bot: sudo rm -rf /opt/p2p-bot"
echo ""
echo -e "${GREEN}Done.${NC}"
