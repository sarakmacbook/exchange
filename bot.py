import os, sys, json, asyncio, logging
from dataclasses import asdict
import httpx
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as KB
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)
from exchanges import Merchant, parse_url, fetch, HEADERS

CONFIG, DB = "config.json", "data.json"
ICON = {"binance": "🟡", "bybit": "🟣", "okx": "⚫", "bitget": "🔵"}
logging.basicConfig(level=logging.INFO)

# ---------------- interactive setup (replaces .env) ----------------
def ask(q, default=None, check=None):
    while True:
        v = input(f"{q}{f' [{default}]' if default else ''}: ").strip() or (default or "")
        if v and (check is None or check(v)): return v
        print("  ❌ Invalid, try again.")

def setup():
    print("\n🤖 P2P Price Bot — first-time setup\n" + "-" * 40)
    cfg = {
        "token":    ask("Bot token from @BotFather", check=lambda v: ":" in v),
        "admins":   ask("Your Telegram user ID(s), comma-separated (get it from @userinfobot)",
                        check=lambda v: all(x.strip().isdigit() for x in v.split(","))),
        "asset":    ask("Asset", "USDT").upper(),
        "fiat":     ask("Fiat currency", "USD").upper(),
        "interval": int(ask("Check prices every N seconds", "60", check=str.isdigit)),
    }
    json.dump(cfg, open(CONFIG, "w"), indent=1)
    print(f"✅ Saved to {CONFIG}. Re-run with  python bot.py --setup  to change.\n")
    return cfg

if "--setup" in sys.argv or not os.path.exists(CONFIG): cfg = setup()
else: cfg = json.load(open(CONFIG))

TOKEN, ASSET, FIAT, INTERVAL = cfg["token"], cfg["asset"], cfg["fiat"], cfg["interval"]
ADMINS = {int(x) for x in cfg["admins"].split(",")}

# ---------------- state ----------------
def load():
    try: return json.load(open(DB))
    except FileNotFoundError: return {"group": None, "auto": False, "merchants": {}, "last": {}}
def save(): json.dump(state, open(DB, "w"), indent=1)
state = load()
merchants = lambda: [Merchant(**m) for m in state["merchants"].values()]
is_admin = lambda u: u.effective_user.id in ADMINS
fmt = lambda p: f"{p:.4f}".rstrip("0").rstrip(".") if p is not None else "—"

# ---------------- panel ----------------
def panel():
    a = state["auto"]
    return KB([[B("📊 Post prices now", callback_data="post"),
                B(f"{'🟢' if a else '🔴'} Auto: {'ON' if a else 'OFF'}", callback_data="auto")],
               [B("📋 Merchants", callback_data="list"), B("🔄 Refresh", callback_data="panel")]])

def panel_text():
    g = state["group"] or "not set — send /setgroup inside your group"
    return (f"🤖 <b>P2P Price Bot</b>\nGroup: <code>{g}</code>\n"
            f"Merchants: {len(state['merchants'])} · Pair: {ASSET}/{FIAT} · every {INTERVAL}s\n\n"
            f"➕ <b>Paste a merchant's public URL here to add it.</b>")

async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if is_admin(u): await u.message.reply_html(panel_text(), reply_markup=panel())

async def setgroup(u: Update, c):
    if not is_admin(u): return
    state["group"] = u.effective_chat.id; save()
    await u.message.reply_text("✅ This group will receive price updates.")

# ---------------- add merchant by pasting URL ----------------
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

# ---------------- prices ----------------
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

# ---------------- buttons ----------------
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

# ---------------- run ----------------
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setgroup", setgroup))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.job_queue.run_repeating(job, interval=INTERVAL, first=5)
    print(f"🚀 Bot running · {ASSET}/{FIAT} · every {INTERVAL}s · Ctrl+C to stop")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
