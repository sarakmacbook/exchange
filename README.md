# 🤖 P2P Merchant Price Bot for Telegram

One‑click Telegram bot that watches specific **P2P merchants** on **Binance, Bybit, OKX and Bitget**
and posts their **best selling price** (merchant sells → you buy) and **best buying price**
(merchant buys → you sell) to your Telegram group — automatically every time the price changes.

Repo: https://github.com/sarakmacbook/exchange

[![⬇️ One-Click Download (ZIP)](https://img.shields.io/badge/⬇️%20One%20Click%20Download%20Source%20(ZIP)-brightgreen)](https://github.com/sarakmacbook/exchange/archive/refs/heads/main.zip)
[![🚀 One-Click Install Script](https://img.shields.io/badge/🚀%20One%20Click%20Install%20Script-blue)](https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh)

## ✨ Features
- 🔗 **Paste a public merchant URL** to the bot → merchant is added instantly (no commands).
- 📊 **One button** posts all merchant prices to your group right now.
- 🟢 **One button** turns auto‑posting ON/OFF (posts only when a price changes).
- 📋 Merchant list with one‑click remove.
- Any asset (USDT, USDC, BTC…) against any fiat (USD, EUR, AED, …).
- Interactive setup — no `.env`, no API keys (or use env vars for Docker).
- Runs as a **systemd service** with auto-restart — survives reboot.

## 📁 Files
| File | Purpose |
|------|---------|
| `bot.py` | Telegram bot: setup wizard, panel, buttons, auto job |
| `exchanges.py` | Binance / Bybit / OKX / Bitget adapters + URL parser |
| `requirements.txt` | Dependencies |
| `install.sh` | **One-click VPS installer** (Ubuntu) |
| `uninstall.sh` | Remove service (keeps data) |
| `Dockerfile` / `docker-compose.yml` | Docker one-click alternative |
| `config.json` | Auto‑created (token, admin IDs, pair, interval) — `chmod 600` |
| `data.json` | Auto‑created; stores group, merchants, last prices |

---

## ⬇️ One-Click Download from GitHub

No git, no cloning — grab the latest source in **one click**:

[![⬇️ Download exchange (ZIP)](https://img.shields.io/badge/⬇️%20Download%20Source%20(ZIP)-brightgreen)](https://github.com/sarakmacbook/exchange/archive/refs/heads/main.zip)

<details>
<summary>Prefer the terminal? (curl / wget)</summary>

```bash
# curl
curl -L -o exchange-main.zip https://github.com/sarakmacbook/exchange/archive/refs/heads/main.zip
unzip exchange-main.zip && cd exchange-main

# or wget
wget https://github.com/sarakmacbook/exchange/archive/refs/heads/main.zip
unzip exchange-main.zip && cd exchange-main
```
</details>

After unzipping, follow [One-Click Install](#-one-click-install-on-ubuntu-vps-2004--2204--2404) (Option B) — `cd exchange-main && sudo bash install.sh`.

---

## 🚀 One-Click Install on Ubuntu VPS (20.04 / 22.04 / 24.04)

> **Fresh VPS? Paste ONE command and you're done.** Tested on clean Ubuntu.

### Option A — Install script, one-liner (fastest)

[`install.sh`](install.sh) is the one‑click install script (source: [raw on GitHub](https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh)). SSH into your VPS, then run:

```bash
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh | bash
```

The installer will:
1. `apt update` + install `python3`, `venv`, `git`
2. Clone/update the bot to `~/exchange` (or `/opt/p2p-bot` if run as root)
3. Create `venv` + `pip install -r requirements.txt`
4. Ask for **bot token / admin IDs / asset / fiat** (interactive wizard)
5. Create `config.json` (`600`) + `data.json`
6. Install & start a **systemd service** (`p2p-bot`) with auto-restart + enable on boot

**Non-interactive (for automation / no TTY):**

```bash
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh | bash -s -- \
  --token "123456:ABC-your-token" \
  --admins "123456789" \
  --asset USDT --fiat USD --interval 60
```

Or via env:

```bash
BOT_TOKEN="123456:ABC" ADMIN_IDS="123456789" \
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh | bash
```

### Option B — Clone + install (recommended if you want to edit)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git

git clone https://github.com/sarakmacbook/exchange.git
cd exchange
sudo bash install.sh
# or: bash install.sh --dir /opt/p2p-bot
```

With flags (no prompts):

```bash
sudo bash install.sh --token "123:ABC" --admins "123456,789012" --asset BTC --fiat EUR --interval 30
```

### Option C — Docker (one-click too)

```bash
git clone https://github.com/sarakmacbook/exchange.git && cd exchange
cp .env.example .env   # edit BOT_TOKEN and ADMIN_IDS
nano .env

docker compose up -d --build
docker compose logs -f
```

Or without `.env`:

```bash
BOT_TOKEN="123:ABC" ADMIN_IDS="123456" docker compose up -d
```

---

## 📱 After install — Telegram setup (2 min)

1. **Talk to your bot privately:** Open your bot on Telegram → `/start` → you'll see the panel.
2. **Set the target group:** Add the bot to your Telegram **group** as admin, then send in the **group**:
   ```
   /setgroup
   ```
   Bot replies `✅ This group will receive price updates.`
3. **Add merchants:** Back in **private chat** with the bot, **paste a merchant's public URL**:
   - Binance: `https://p2p.binance.com/en/advertiserDetail?advertiserNo=...`
   - Bybit: `https://www.bybit.com/en/fiat/trade/otc/profile/123456/USDT/USD`
   - OKX: `https://www.okx.com/p2p/market?publicUserId=...`
   - Bitget: `https://www.bitget.com/p2p/merchant/xxxxx`
   
   Bot will check and confirm with sell/buy prices.
4. Use panel buttons:
   - **📊 Post prices now** — push current prices to group
   - **🟢/🔴 Auto** — toggle auto-post when prices change
   - **📋 Merchants** — list & tap to remove

> Tip: you can paste the same merchant URL multiple times — it's deduplicated by `exchange + merchant_id + asset/fiat`.

---

## 🛠️ Managing the bot on VPS

```bash
sudo systemctl status p2p-bot          # check if running
sudo journalctl -u p2p-bot -f           # live logs (Ctrl+C to exit)
sudo journalctl -u p2p-bot -n 100       # last 100 lines
sudo systemctl restart p2p-bot          # restart
sudo systemctl stop p2p-bot             # stop
sudo systemctl start p2p-bot            # start
```

**Reconfigure (change token / pair / interval):**

```bash
sudo bash ~/exchange/install.sh --reconfigure
# or if installed to /opt:
sudo bash /opt/p2p-bot/install.sh --reconfigure
```

**Update to latest code:**

```bash
sudo bash ~/exchange/install.sh --update
# pulls git + pip install + restarts service
# alternative: cd ~/exchange && git pull && sudo systemctl restart p2p-bot
```

**Uninstall:** see the dedicated section below — [🗑️ Uninstall](#-uninstall).

---

## 🐳 Docker management

```bash
docker compose logs -f          # logs
docker compose restart          # restart
docker compose down             # stop
docker compose up -d --build    # update after git pull
```

Env vars override `config.json` — set `BOT_TOKEN`, `ADMIN_IDS`, `ASSET`, `FIAT`, `INTERVAL` in `.env` or `docker-compose.yml`.

---

## 🗑️ Uninstall

### Option 1 — uninstall script (recommended, keeps your data)

```bash
# if installed as a regular user
bash ~/exchange/uninstall.sh

# if installed as root (to /opt/p2p-bot)
sudo bash /opt/p2p-bot/uninstall.sh
```

### Option 2 — via the installer

```bash
sudo bash ~/exchange/install.sh --uninstall
```

Both **stop the service, remove the systemd unit, kill any running bot, and clean the cron entry** — but keep `config.json` and `data.json` so a reinstall restores your merchants instantly.

### Full wipe (delete code + data)

```bash
# regular-user install
rm -rf ~/exchange

# root install
sudo rm -rf /opt/p2p-bot
```

### Docker

```bash
cd ~/exchange          # or wherever you cloned it
docker compose down    # stop + remove containers
rm -rf ~/exchange      # delete code + .env (data lived in config.json/data.json)
```

---

## 🔧 Manual run (without systemd)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python bot.py              # wizard on first run
python bot.py --setup      # re-run wizard
python bot.py --token 123:ABC --admins 123456 --asset USDT --fiat USD  # non-interactive
```

---

## ❓ Troubleshooting

**`config.json not found and no BOT_TOKEN`**
- Run `python bot.py --setup` interactively, or pass `--token`/`--admins`.

**Bot doesn't post:**
- Did you send `/setgroup` **inside the group** (not private chat)?
- Is **Auto ON** (🟢) or press **📊 Post now** to force?
- Check logs: `sudo journalctl -u p2p-bot -n 50`

**`⚠️ Set group and add merchants first`**
- You need at least one merchant + a group set.

**Service fails:**
```bash
sudo journalctl -u p2p-bot -n 100 --no-pager
sudo systemctl status p2p-bot --no-pager
~/exchange/venv/bin/python ~/exchange/bot.py   # run manually to see error
```

**Python < 3.8**
- Ubuntu 20.04 has 3.8 (works). For older, `sudo apt install python3.11`.

---

## 🔒 Security
- `config.json` and `data.json` are `chmod 600` (owner-only).
- Bot uses **long polling** — no inbound ports, no webhook, no firewall rules needed.
- Runs as your user (or `ubuntu`) — not root — via systemd `User=`.
- Token never logged.

---

## 📄 License
MIT — do what you want. PRs welcome.
