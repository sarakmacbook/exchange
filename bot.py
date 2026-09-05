import os, json, asyncio, logging
from dataclasses import asdict
import httpx
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as KB
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from exchanges import Merchant, parse_url, fetch, HEADERS

TOKEN = os.environ["BOT_TOKEN"]
ADMINS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}
ASSET, FIAT = os.environ.get("DEFAULT_ASSET", "USDT"), os.environ.get("DEFAULT_FIAT", "USD")
INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))
DB = "data.json"
logging.basicConfig(level=logging.INFO)

def load():
    try: return json.load(open(DB))
    except FileNotFoundError: return {"group": None, "auto": False, "merchants": {}, "last": {}}
def save(): json.dump(state, open(DB, "w"), indent=1)
state = load()
merchants = lambda: [Merchant(**m) for m in state["merchants"].values()]
is_admin = lambda u: not ADMINS or u.effective_user.id in ADMINS

# ---------------- one-click panel ----------------
def panel():
    return KB([[B("📊 Post prices now", callback_data="post"),
                B(f"{'🟢' if state['auto'] else '🔴'} Auto: {'ON' if state['auto'] else 'OFF'}", callback_data="auto")],
               [B("📋 Merchants", callback_data="list"), B("🔄 Refresh", callback_data="panel")]])

def panel_text():
    g = state["group"] or "not set — send /setgroup inside your group"
    return (f"🤖 <b>P2P Price Bot</b>\nGroup: <code>{g}</code>\nMerchants: {len(state['merchants'])}\n"
            f"Pair: {ASSET}/{FIAT} · check every {INTERVAL}s\n
