import os, sys, json, asyncio, logging, argparse, signal
from dataclasses import asdict
from pathlib import Path
import httpx
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as KB
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ChatMemberHandler, ContextTypes, filters)
from exchanges import Merchant, parse_url, fetch, HEADERS

# ── paths: always relative to this file (works with systemd WorkingDirectory) ──
BASE_DIR = Path(__file__).resolve().parent
CONFIG = BASE_DIR / "config.json"
DB = BASE_DIR / "data.json"

ICON = {"binance": "🟡", "bybit": "🟣", "okx": "⚫", "bitget": "🔵"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("p2p-bot")

# ── CLI / ENV ──
def parse_cli():
    p = argparse.ArgumentParser(description="P2P Merchant Price Bot", add_help=True)
    p.add_argument("--setup", action="store_true", help="Re-run interactive setup wizard")
    p.add_argument("--reconfigure", action="store_true", help="Alias for --setup")
    p.add_argument("--token", help="Bot token from @BotFather")
    p.add_argument("--admins", help="Telegram user ID(s), comma-separated")
    p.add_argument("--asset", help="Asset, e.g. USDT")
    p.add_argument("--fiat", help="Fiat, e.g. USD")
    p.add_argument("--interval", type=int, help="Check interval seconds")
    return p.parse_args()

CLI = parse_cli()
if CLI.reconfigure:
    CLI.setup = True

# ── config helpers ──
def ask(q, default=None, check=None):
    while True:
        v = input(f"{q}{f' [{default}]' if default else ''}: ").strip() or (default or "")
        if v and (check is None or check(v)): return v
        print("  ❌ Invalid, try again.")

def env_or_cli(name_envs, cli_val, default=None):
    # name_envs: list of env var names to try
    for n in name_envs:
        v = os.getenv(n)
        if v: return v.strip()
    if cli_val: return str(cli_val).strip()
    return default

def setup_interactive(existing=None):
    print("\n🤖 P2P Price Bot — first-time setup\n" + "-" * 40)
    print("  Get token from @BotFather → /newbot")
    print("  Get your ID from @userinfobot\n")
    # prefill from env/cli/existing
    def prefill(key, envs, cli_v, fallback):
        if existing and existing.get(key): return str(existing[key])
        v = env_or_cli(envs, cli_v, None)
        return v if v else fallback
    cfg = {
        "token":    ask("Bot token from @BotFather",
                        prefill("token", ["BOT_TOKEN","TELEGRAM_BOT_TOKEN","TOKEN"], CLI.token, None),
                        check=lambda v: ":" in v),
        "admins":   ask("Your Telegram user ID(s), comma-separated (from @userinfobot)",
                        prefill("admins", ["ADMIN_IDS","ADMINS"], CLI.admins, None),
                        check=lambda v: all(x.strip().isdigit() for x in v.split(","))),
        "asset":    ask("Asset", prefill("asset", ["ASSET"], CLI.asset, "USDT")).upper(),
        "fiat":     ask("Fiat currency", prefill("fiat", ["FIAT"], CLI.fiat, "USD")).upper(),
        "interval": int(ask("Check prices every N seconds",
                            str(prefill("interval", ["INTERVAL"], CLI.interval, "60")), check=str.isdigit)),
    }
    json.dump(cfg, open(CONFIG, "w"), indent=1)
    try: os.chmod(CONFIG, 0o600)
    except Exception: pass
    print(f"✅ Saved to {CONFIG}. Re-run with  python bot.py --setup  to change.\n")
    return cfg

def load_config():
    # 1. try file
    file_cfg = {}
    if CONFIG.exists():
        try: file_cfg = json.loads(CONFIG.read_text())
        except Exception as e:
            log.warning("config.json unreadable: %s — will recreate", e)
            file_cfg = {}

    # 2. overrides from env/cli (highest priority)
    #    If env provides token+admins we treat it as authoritative and persist to file
    env_token = env_or_cli(["BOT_TOKEN","TELEGRAM_BOT_TOKEN","TOKEN"], CLI.token)
    env_admins = env_or_cli(["ADMIN_IDS","ADMINS"], CLI.admins)
    env_asset = env_or_cli(["ASSET"], CLI.asset)
    env_fiat = env_or_cli(["FIAT"], CLI.fiat)
    env_interval = env_or_cli(["INTERVAL"], CLI.interval)

    # If CLI --setup requested, force interactive (prefilled from env/file)
    if CLI.setup:
        merged = dict(file_cfg)
        # pre-apply env/cli so wizard shows them as defaults
        if env_token: merged["token"] = env_token
        if env_admins: merged["admins"] = env_admins
        if env_asset: merged["asset"] = env_asset.upper()
        if env_fiat: merged["fiat"] = env_fiat.upper()
        if env_interval: merged["interval"] = int(str(env_interval).strip())
        return setup_interactive(merged)

    # If file missing but env provides minimum (token+admins) → create without prompting
    if not file_cfg and env_token and env_admins:
        log.info("Creating config.json from environment variables")
        cfg = {
            "token": env_token,
            "admins": env_admins.replace(" ", ""),
            "asset": (env_asset or "USDT").upper(),
            "fiat": (env_fiat or "USD").upper(),
            "interval": int(str(env_interval or "60").strip()),
        }
        # validate
        if ":" not in cfg["token"]:
            log.error("BOT_TOKEN invalid (missing ':')")
            sys.exit(1)
        json.dump(cfg, open(CONFIG, "w"), indent=1)
        try: os.chmod(CONFIG, 0o600)
        except: pass
        return cfg

    # If file exists, apply env overrides (env wins, and we persist)
    if file_cfg:
        dirty = False
        if env_token and env_token != file_cfg.get("token"):
            file_cfg["token"] = env_token; dirty = True; log.info("Overriding token from env")
        if env_admins and env_admins.replace(" ","") != file_cfg.get("admins"):
            file_cfg["admins"] = env_admins.replace(" ",""); dirty = True; log.info("Overriding admins from env")
        if env_asset and env_asset.upper() != file_cfg.get("asset"):
            file_cfg["asset"] = env_asset.upper(); dirty = True
        if env_fiat and env_fiat.upper() != file_cfg.get("fiat"):
            file_cfg["fiat"] = env_fiat.upper(); dirty = True
        if env_interval and str(env_interval) != str(file_cfg.get("interval")):
            try: file_cfg["interval"] = int(str(env_interval).strip()); dirty=True
            except: pass
        if dirty:
            json.dump(file_cfg, open(CONFIG, "w"), indent=1)
            try: os.chmod(CONFIG, 0o600)
            except: pass
        return file_cfg

    # No file, no env → interactive if TTY, else error
    if sys.stdin.isatty():
        return setup_interactive(file_cfg)
    else:
        log.error("config.json not found and no BOT_TOKEN/ADMIN_IDS env provided.")
        log.error("Run interactively:  python bot.py --setup")
        log.error("Or set env:  BOT_TOKEN=123:ABC ADMIN_IDS=123456 python bot.py")
        log.error("Or use installer:  bash install.sh --token 123:ABC --admins 123456")
        sys.exit(1)

cfg = load_config()

TOKEN, ASSET, FIAT, INTERVAL = cfg["token"], cfg["asset"], cfg["fiat"], int(cfg["interval"])
try:
    ADMINS = {int(x.strip()) for x in cfg["admins"].split(",") if x.strip()}
except Exception:
    log.error("admins field invalid: %r — should be comma-separated IDs", cfg.get("admins"))
    sys.exit(1)

if ":" not in TOKEN:
    log.error("token invalid — should contain ':'")
    sys.exit(1)

# ── state ──
def load():
    try: return json.loads(DB.read_text())
    except FileNotFoundError: return {"group": None, "auto": False, "merchants": {}, "last": {}}
    except Exception as e:
        log.warning("data.json unreadable: %s — resetting", e)
        return {"group": None, "auto": False, "merchants": {}, "last": {}}
def save(): 
    DB.write_text(json.dumps(state, indent=1))
    try: os.chmod(DB, 0o600)
    except: pass
state = load()
merchants = lambda: [Merchant(**m) for m in state["merchants"].values()]
is_admin = lambda u: u.effective_user and u.effective_user.id in ADMINS
fmt = lambda p: f"{p:.4f}".rstrip("0").rstrip(".") if p is not None else "—"

# ── panel ──
BOT_USERNAME = None  # filled in post_init

def set_group_button():
    # One click: opens Telegram's "choose a group" picker, adds the bot, and the
    # group is registered automatically (via /start setgroup + my_chat_member).
    label = "👥 Change group" if state["group"] else "👥 Set group"
    if BOT_USERNAME:
        return B(label, url=f"https://t.me/{BOT_USERNAME}?startgroup=setgroup")
    return B(label, callback_data="setgroup_help")

def panel():
    a = state["auto"]
    return KB([[B("📊 Post prices now", callback_data="post"),
                B(f"{'🟢' if a else '🔴'} Auto: {'ON' if a else 'OFF'}", callback_data="auto")],
               [B("📋 Merchants", callback_data="list"), set_group_button()],
               [B("🔄 Refresh", callback_data="panel")]])

def group_label():
    if not state["group"]: return None
    t = state.get("group_title")
    return f"{t} ({state['group']})" if t else str(state["group"])

def panel_text():
    g = group_label() or "not set — tap 👥 Set group below"
    return (f"🤖 <b>P2P Price Bot</b>\nGroup: <code>{g}</code>\n"
            f"Merchants: {len(state['merchants'])} · Pair: {ASSET}/{FIAT} · every {INTERVAL}s\n\n"
            f"➕ <b>Paste a merchant's public URL here to add it.</b>")

def _set_group(chat):
    state["group"] = chat.id
    state["group_title"] = chat.title or ""
    state["last"] = {}  # force a fresh post to the new group
    save()

async def notify_admins(bot, text):
    for a in ADMINS:
        try: await bot.send_message(a, text, parse_mode="HTML", reply_markup=panel())
        except Exception: pass

async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    chat = u.effective_chat
    if chat.type in ("group", "supergroup"):
        # /start setgroup arrives when the bot is added via the 👥 Set group button
        if c.args and c.args[0] == "setgroup":
            if not is_admin(u): return
            _set_group(chat)
            await u.message.reply_text(f"✅ <b>{chat.title}</b> will receive price updates.", parse_mode="HTML")
            await notify_admins(c.bot, f"✅ Group set to <b>{chat.title}</b>")
        return
    if is_admin(u): await u.message.reply_html(panel_text(), reply_markup=panel())
    else: await u.message.reply_text("⛔ You are not authorized. Ask the bot admin to add your ID.")

async def setgroup(u: Update, c):
    if not is_admin(u): return
    if u.effective_chat.type == "private":
        return await u.message.reply_html("Use the 👥 <b>Set group</b> button, or send /setgroup inside your group.",
                                          reply_markup=panel())
    _set_group(u.effective_chat)
    await u.message.reply_text("✅ This group will receive price updates.")

async def on_my_chat_member(u: Update, c):
    """Auto-register the group when an admin adds the bot to it (no command needed)."""
    m = u.my_chat_member
    chat = m.chat
    if chat.type not in ("group", "supergroup"): return
    was, now = m.old_chat_member.status, m.new_chat_member.status
    joined = was in ("left", "kicked") and now in ("member", "administrator")
    if joined and m.from_user and m.from_user.id in ADMINS and state["group"] != chat.id:
        _set_group(chat)
        try: await c.bot.send_message(chat.id, f"✅ <b>{chat.title}</b> will receive price updates.", parse_mode="HTML")
        except Exception: pass
        await notify_admins(c.bot, f"✅ Group set to <b>{chat.title}</b>")
    elif now in ("left", "kicked") and state["group"] == chat.id:
        state["group"] = None; state["group_title"] = ""; save()
        await notify_admins(c.bot, f"⚠️ Bot was removed from <b>{chat.title}</b> — group unset.")

# ── add merchant by pasting URL ──
async def on_text(u: Update, c):
    if not is_admin(u) or u.effective_chat.type != "private": return
    m = parse_url(u.message.text, ASSET, FIAT)
    if not m: return await u.message.reply_text("❌ Not a supported merchant URL (Binance / Bybit / OKX / Bitget).")
    msg = await u.message.reply_text("⏳ Checking merchant…")
    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as cl:
        r = await fetch(cl, m)
    state["merchants"][m.key] = asdict(m); save()
    await msg.edit_text(f"✅ Added {ICON[m.exchange]} {m.exchange.title()} · {m.nickname or m.merchant_id}\n"
                        f"Sell: {fmt(r['sell'])} · Buy: {fmt(r['buy'])}")
    await u.message.reply_html(panel_text(), reply_markup=panel())

# ── prices ──
async def get_prices():
    ms = merchants()
    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as cl:
        res = await asyncio.gather(*(fetch(cl, m) for m in ms))
    out = {}
    for m, r in zip(ms, res):
        state["merchants"][m.key] = asdict(m)
        out[m.key] = r
    save(); return out

def report(prices):
    lines = [f"📊 <b>P2P {ASSET}/{FIAT}</b>\n"]
    for m in merchants():
        r = prices[m.key]
        lines.append(f"{ICON[m.exchange]} <b>{m.exchange.title()}</b> · "
                     f"<a href=\"{m.url}\">{m.nickname or m.merchant_id}</a>")
        if r["error"]: lines.append(f"   ⚠️ {r['error']}\n"); continue
        lines.append(f"   🔴 Best SELL (you buy): <b>{fmt(r['sell'])}</b>\n"
                     f"   🟢 Best BUY  (you sell): <b>{fmt(r['buy'])}</b>\n")
    return "\n".join(lines)

async def post(bot, force=False):
    if not state["group"] or not state["merchants"]: return False
    prices = await get_prices()
    snap = {k: [v["sell"], v["buy"]] for k, v in prices.items()}
    if not force and snap == state["last"]: return False
    state["last"] = snap; save()
    await bot.send_message(state["group"], report(prices), parse_mode="HTML", disable_web_page_preview=True)
    return True

async def job(c: ContextTypes.DEFAULT_TYPE):
    if state["auto"]:
        try: await post(c.bot)
        except Exception as e: logging.warning("auto post failed: %s", e)

# ── buttons ──
def list_kb():
    rows = [[B(f"❌ {ICON[m.exchange]} {m.exchange.title()} · {m.nickname or m.merchant_id}",
               callback_data=f"del:{m.key}")] for m in merchants()]
    return KB(rows + [[B("⬅️ Back", callback_data="panel")]])

async def on_button(u: Update, c):
    q = u.callback_query
    if not is_admin(u): return await q.answer()
    d = q.data
    if d == "post":
        ok = await post(c.bot, force=True)
        await q.answer("✅ Posted!" if ok else "⚠️ Set group (/setgroup) and add merchants first", show_alert=not ok)
    elif d == "auto":
        state["auto"] = not state["auto"]; save(); await q.answer()
    elif d == "setgroup_help":
        return await q.answer("Add the bot to your group, then send /setgroup there.", show_alert=True)
    elif d == "list":
        await q.answer()
        return await q.edit_message_text("📋 <b>Merchants</b> — tap to remove" if state["merchants"]
                                         else "📋 No merchants yet. Paste a URL to add one.",
                                         parse_mode="HTML", reply_markup=list_kb())
    elif d.startswith("del:"):
        state["merchants"].pop(d[4:], None); state["last"].pop(d[4:], None); save()
        await q.answer("🗑 Removed")
        return await q.edit_message_text("📋 <b>Merchants</b> — tap to remove", parse_mode="HTML", reply_markup=list_kb())
    else:
        await q.answer()
    try: await q.edit_message_text(panel_text(), parse_mode="HTML", reply_markup=panel())
    except Exception: pass  # unchanged content

async def error_handler(update, context):
    log.warning("Update %s caused error %s", update, context.error)

# ── run ──
def main():
    # graceful shutdown for systemd
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: signal.signal(sig, lambda *_: sys.exit(0))
        except: pass

    async def post_init(application):
        global BOT_USERNAME
        me = await application.bot.get_me()
        BOT_USERNAME = me.username
        log.info("Logged in as @%s", BOT_USERNAME)

    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setgroup", setgroup))
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(error_handler)
    app.job_queue.run_repeating(job, interval=INTERVAL, first=5)
    print(f"🚀 Bot running · {ASSET}/{FIAT} · every {INTERVAL}s · Ctrl+C to stop")
    print(f"   Admins: {', '.join(map(str, ADMINS))} · Group: {state['group'] or 'not set'} · Merchants: {len(state['merchants'])}")
    if not state["group"]:
        print("   → Open the bot in Telegram, /start, tap 👥 Set group")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
