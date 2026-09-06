# 🤖 P2P Merchant Price Bot

Telegram bot that watches your favourite **P2P merchants** on **Binance · Bybit · OKX · Bitget** and posts their best **sell** / **buy** prices to your Telegram group — automatically, every time the price changes.

---

## ⚡ One-Click Install

Paste this on a fresh Ubuntu VPS (20.04 / 22.04 / 24.04):

```bash
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh | bash
```

That's it. The installer sets up Python, installs the bot, asks for your **bot token** and **Telegram ID**, and starts it as a `systemd` service that survives reboots.

<details>
<summary>No prompts (for automation)</summary>

```bash
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/install.sh | bash -s -- \
  --token "123456:ABC-your-token" --admins "123456789" --asset USDT --fiat USD --interval 60
```
</details>

<details>
<summary>Docker instead</summary>

```bash
git clone https://github.com/sarakmacbook/exchange.git && cd exchange
cp .env.example .env && nano .env      # BOT_TOKEN + ADMIN_IDS
docker compose up -d --build
```
</details>

> Need a token? Telegram → [@BotFather](https://t.me/BotFather) → `/newbot`.
> Need your ID? Telegram → [@userinfobot](https://t.me/userinfobot).

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
| 🔄 **Refresh** | Refresh the panel |

---

## 🛠️ Manage

```bash
sudo systemctl status p2p-bot     # is it running?
sudo journalctl -u p2p-bot -f     # live logs
sudo systemctl restart p2p-bot    # restart

sudo bash install.sh --reconfigure   # change token / pair / interval
sudo bash install.sh --update        # pull latest + restart
```

**Uninstall (keeps your data):**

```bash
curl -fsSL https://raw.githubusercontent.com/sarakmacbook/exchange/main/uninstall.sh | bash
```

---

## 📁 Files

| File | Purpose |
|---|---|
| `bot.py` | Telegram bot (panel, buttons, auto-poster) |
| `exchanges.py` | Binance / Bybit / OKX / Bitget adapters + URL parser |
| `install.sh` / `uninstall.sh` | One-click installer / uninstaller |
| `Dockerfile` / `docker-compose.yml` | Docker alternative |
| `config.json` | Auto-created: token, admins, pair, interval |
| `data.json` | Auto-created: group, merchants, last prices |

## 📄 License

MIT
