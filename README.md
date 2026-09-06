## ⚡ One-Click Install

```bash
wget https://raw.githubusercontent.com/sarakmacbook/exchange/refs/heads/main/install.sh

chmod +x install.sh

./install.sh
```

## ⚡ One-Click Uninstall
```bash
https://raw.githubusercontent.com/sarakmacbook/exchange/refs/heads/main/uninstall.sh

chmod +x uninstall.sh

./uninstall.sh
```


# 🤖 P2P Merchant Price Bot

Telegram bot that watches your favourite **P2P merchants** on **Binance · Bybit · OKX · Bitget** and posts their best **sell** / **buy** prices to your Telegram group — automatically, every time the price changes.

---

## ⚡ One-Click Install

Pick the installer that matches your machine — all four ask for your **bot token** (from [@BotFather](https://t.me/BotFather) → `/newbot`) and your **Telegram ID** (from [@userinfobot](https://t.me/userinfobot)), then start the bot.

| Installer | Best for | What it does |
|---|---|---|
| `install.sh` | Ubuntu/Debian **VPS with systemd** | venv + systemd service (auto-restart & reboot-safe) |
| `install-docker.sh` | Any machine **with Docker**, incl. macOS | Docker Compose container (`restart: unless-stopped`) |
| `install-local.sh` | **macOS / Linux without systemd / WSL** | venv + nohup + launchd (macOS) or cron `@reboot` autostart |
| **python3 one-liner** | **Any machine with Python 3** (no curl / wget needed) | Downloads + runs `install-local.sh` in one command |

> **curl or wget — your choice.** Every one-liner below is shown with both `curl` and `wget`; they are interchangeable. Inside the scripts the same applies: downloads automatically use **curl → wget → python3**, whichever exists on the box, and `git` is optional (a tarball is fetched instead when git is missing). Force a specific tool with `DOWNLOADER=wget`.

### Option A — VPS with systemd (recommended)

Paste this on a fresh Ubuntu VPS (20.04 / 22.04 / 24.04):

```bash
# with curl
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh | bash

# with wget
wget -qO- https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh | bash
```

### Option B — Docker (macOS, Windows, any Linux)

```bash
# with curl
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install-docker.sh | bash

# with wget
wget -qO- https://raw.githubusercontent.com/sarakmacbook/exchange/main/install-docker.sh | bash
```

The script checks/installs Docker, creates `config.json` + `.env`, and runs `docker compose up -d --build`.

### Option C — Local / no systemd (laptops, WSL, shared hosting)

```bash
# with curl
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install-local.sh | bash

# with wget
wget -qO- https://raw.githubusercontent.com/sarakmacbook/exchange/main/install-local.sh | bash
```

### Option D — Python 3 (no curl / no wget)

One-click install with nothing but **Python 3** installed. It downloads `install-local.sh` and runs it:

```bash
python3 -c "import urllib.request as u;print(u.urlopen('https://raw.githubusercontent.com/sarakmacbook/exchange/main/install-local.sh').read().decode())" | bash
```

> This is the same local / no-systemd install as **Option C**, just launched by Python instead of `curl` or `wget`.

<details>
<summary>No curl and no wget? (python3 / PowerShell / manual)</summary>

**python3 (any Linux/macOS with Python 3):** use **Option D** above — one command, no curl/wget needed.

**Windows PowerShell** (then run it with WSL or Git Bash):

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/sarakmacbook/exchange/main/install-local.sh -OutFile install-local.sh
bash install-local.sh
```

**Fully manual — download the archive, no git needed:**

```bash
mkdir -p ~/exchange && wget -qO- https://codeload.github.com/sarakmacbook/exchange/tar.gz/refs/heads/main | tar -xz --strip-components=1 -C ~/exchange
cd ~/exchange && bash install-local.sh        # or: sudo bash install.sh
```

(With curl instead of wget: `curl -fsSL https://codeload.github.com/sarakmacbook/exchange/tar.gz/refs/heads/main | tar -xz --strip-components=1 -C ~/exchange`)
</details>

<details>
<summary>No prompts (for automation) — any installer</summary>

```bash
# curl
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh | bash -s -- \
  --token "123456:ABC-your-token" --admins "123456789" --asset USDT --fiat USD --interval 60

# wget
wget -qO- https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh | bash -s -- \
  --token "123456:ABC-your-token" --admins "123456789" --asset USDT --fiat USD --interval 60
```
</details>

<details>
<summary>Docker without the installer</summary>

```bash
git clone https://github.com/sarakmacbook/exchange.git && cd exchange
cp .env.example .env && nano .env      # BOT_TOKEN + ADMIN_IDS
docker compose up -d --build
```
</details>

---

## 📱 Setup in Telegram (1 minute)

1. Open your bot → `/start`
2. Tap **👥 Set group** → pick your group → done. The bot joins and registers the group automatically.
3. **Paste a merchant URL** into the bot chat to add it:
   - `https://p2p.binance.com/en/advertiserDetail?advertiserNo=…`
   - `https://www.bybit.com/en/fiat/trade/otc/profile/…`
   - `https://www.okx.com/p2p/market?publicUserId=…`
   - `https://www.bitget.com/p2p/merchant/…`
4. Tap **🟢 Auto: ON** — prices are posted whenever they change.

### Panel buttons

| Button | What it does |
|---|---|
| 📊 **Post prices now** | Posts all merchant prices to the group immediately |
| 🟢/🔴 **Auto** | Toggle automatic posting on price change |
| 📋 **Merchants** | List merchants — tap one to remove |
| 👥 **Set group** | One click: choose the group that receives updates |
| ⚙️ **Settings** | Liquidity, Buy/Sell buttons, auto-delete timers, **join/left cleanup** |
| 📝 **Custom Msg** | Customize the **full** post: header, body (per-merchant template), footer |
| 👁 **Preview** | See exactly how the group post will look |
| 🔄 **Refresh** | Refresh the panel |

### 📝 Custom message — header, body & footer

Tap **📝 Custom Msg** (or ⚙️ Settings → Edit) to fully customize the group post:

- **Header** — shown once on top (default: `📊 P2P {ASSET}/{FIAT}`).
- **Body** — a template repeated **once per merchant**. Leave it default or write your own.
- **Footer** — shown once at the bottom (default: none).

**Body placeholders** (also `{ASSET}`, `{FIAT}`, `{PAIR}` work everywhere):

| Placeholder | Replaced with |
|---|---|
| `{ICON}` | Exchange emoji (🟡 🟣 ⚫ 🔵) |
| `{EXCHANGE}` | Exchange name, e.g. `Binance` |
| `{NICK}` | Merchant nickname |
| `{LINK}` | Clickable merchant name (`<a>` to the profile) |
| `{URL}` | Raw merchant profile URL |
| `{SELL}` / `{BUY}` | Best sell / buy price |
| `{SELL_AMOUNT}` / `{BUY_AMOUNT}` | Available liquidity (if the merchant has ads) |
| `{ERROR}` | Fetch error text, if any |

HTML (`<b>`, `<i>`, `<code>`, `<a href>`) and new lines are supported. Example 3-line body:

```
{ICON} <b>{EXCHANGE}</b> · {LINK}
🔴 Sell: <b>{SELL}</b> 💧 {SELL_AMOUNT} {ASSET}
🟢 Buy: <b>{BUY}</b> 💧 {BUY_AMOUNT} {ASSET}
```

Use **👁 Preview** to check the result before it goes to the group.

### 🚪 Auto-delete “joined / left the group” messages

The bot deletes Telegram’s **“X joined the group”** and **“X left the group”** service messages in your group — including when people join after being **accepted via a join request** — so your price feed stays clean.

- Toggle in ⚙️ **Settings → 🚪 Del Join/Left msgs** (ON by default).
- ⚠️ The bot must be a **group admin** with the **Delete messages** permission, otherwise it can't remove those messages.

---

## 🛠️ Manage

**systemd (Option A):**

```bash
sudo systemctl status p2p-bot     # is it running?
sudo journalctl -u p2p-bot -f     # live logs
sudo systemctl restart p2p-bot    # restart
sudo bash install.sh --reconfigure   # change token / pair / interval
sudo bash install.sh --update        # pull latest + restart
```

**Docker (Option B):**

```bash
docker compose ps             # status
docker compose logs -f        # live logs
docker compose restart        # restart
bash install-docker.sh --reconfigure   # change token / pair / interval
bash install-docker.sh --update        # pull latest + rebuild + restart
bash install-docker.sh --down          # stop container (keep data)
```

**Local / no systemd (Option C):**

```bash
tail -f ~/exchange-local/bot.log   # live logs (or $INSTALL_DIR/bot.log)
bash install-local.sh --stop       # stop (start again by re-running install-local.sh)
bash install-local.sh --reconfigure  # change token / pair / interval
bash install-local.sh --update        # pull latest + restart
bash install-local.sh --uninstall     # stop + remove autostart (keep data)
```

**Uninstall (keeps your data):**

```bash
# systemd install
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/uninstall.sh | bash
# …or the same with wget
wget -qO- https://raw.githubusercontent.com/sarakmacbook/exchange/main/uninstall.sh | bash
# docker install
bash install-docker.sh --down
# local install
bash install-local.sh --uninstall
```

---

## 📁 Files

| File | Purpose |
|---|---|
| `bot.py` | Telegram bot (panel, buttons, auto-poster) |
| `exchanges.py` | Binance / Bybit / OKX / Bitget adapters + URL parser |
| `install.sh` | One-click installer — systemd VPS |
| `install-docker.sh` | One-click installer — Docker Compose |
| `install-local.sh` | One-click installer — macOS / no systemd |
| `uninstall.sh` | Remove systemd service (keeps data) |
| `Dockerfile` / `docker-compose.yml` | Docker alternative |
| `config.json` | Auto-created: token, admins, pair, interval |
| `data.json` | Auto-created: group, merchants, last prices |

All three installers download what they need with **curl, wget or python3** (first one found — override with `DOWNLOADER=wget`), and fall back to the GitHub tarball when `git` is not installed.

## 📄 License

MIT
