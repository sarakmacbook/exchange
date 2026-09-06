import os, sys, json, asyncio, logging, argparse, signal, time, re
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
    for n in name_envs:
        v = os.getenv(n)
        if v: return v.strip()
    if cli_val: return str(cli_val).strip()
    return default

def setup_interactive(existing=None):
    print("\n🤖 P2P Price Bot — first-time setup\n" + "-" * 40)
    print("  Get token from @BotFather → /newbot")
    print("  Get your ID from @userinfobot\n")
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
    file_cfg = {}
    if CONFIG.exists():
        try: file_cfg = json.loads(CONFIG.read_text())
        except Exception as e:
            log.warning("config.json unreadable: %s — will recreate", e)
            file_cfg = {}

    env_token = env_or_cli(["BOT_TOKEN","TELEGRAM_BOT_TOKEN","TOKEN"], CLI.token)
    env_admins = env_or_cli(["ADMIN_IDS","ADMINS"], CLI.admins)
    env_asset = env_or_cli(["ASSET"], CLI.asset)
    env_fiat = env_or_cli(["FIAT"], CLI.fiat)
    env_interval = env_or_cli(["INTERVAL"], CLI.interval)

    if CLI.setup:
        merged = dict(file_cfg)
        if env_token: merged["token"] = env_token
        if env_admins: merged["admins"] = env_admins
        if env_asset: merged["asset"] = env_asset.upper()
        if env_fiat: merged["fiat"] = env_fiat.upper()
        if env_interval: merged["interval"] = int(str(env_interval).strip())
        return setup_interactive(merged)

    if not file_cfg and env_token and env_admins:
        log.info("Creating config.json from environment variables")
        cfg = {
            "token": env_token,
            "admins": env_admins.replace(" ", ""),
            "asset": (env_asset or "USDT").upper(),
            "fiat": (env_fiat or "USD").upper(),
            "interval": int(str(env_interval or "60").strip()),
        }
        if ":" not in cfg["token"]:
            log.error("BOT_TOKEN invalid (missing ':')")
            sys.exit(1)
        json.dump(cfg, open(CONFIG, "w"), indent=1)
        try: os.chmod(CONFIG, 0o600)
        except: pass
        return cfg

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
DEFAULT_SETTINGS = {
    "show_liquidity": False,
    "show_buttons": True,
    "custom_header": "",
    "custom_body": "",     # per-merchant line template for the group post
    "custom_footer": "",
    "auto_delete": True,  # delete previous group message on new post
    "delete_after_hours": 24,  # auto delete after 24h
    "delete_join_left": True  # delete Telegram "X joined/left the group" service messages
}

def load():
    try:
        data = json.loads(DB.read_text())
    except FileNotFoundError:
        data = {"group": None, "auto": False, "merchants": {}, "last": {}, "settings": DEFAULT_SETTINGS.copy(), "last_msg_id": None, "last_msg_time": None}
    except Exception as e:
        log.warning("data.json unreadable: %s — resetting", e)
        data = {"group": None, "auto": False, "merchants": {}, "last": {}, "settings": DEFAULT_SETTINGS.copy(), "last_msg_id": None, "last_msg_time": None}
    # migration: ensure keys exist
    if "settings" not in data or not isinstance(data["settings"], dict):
        data["settings"] = DEFAULT_SETTINGS.copy()
    for k, v in DEFAULT_SETTINGS.items():
        if k not in data["settings"]:
            data["settings"][k] = v
    if "last" not in data:
        data["last"] = {}
    if "merchants" not in data:
        data["merchants"] = {}
    if "auto" not in data:
        data["auto"] = False
    if "group" not in data:
        data["group"] = None
    if "last_msg_id" not in data:
        data["last_msg_id"] = None
    if "last_msg_time" not in data:
        data["last_msg_time"] = None
    return data

def save(): 
    DB.write_text(json.dumps(state, indent=1))
    try: os.chmod(DB, 0o600)
    except: pass

state = load()
merchants = lambda: [Merchant(**m) for m in state["merchants"].values()]
is_admin = lambda u: u.effective_user and u.effective_user.id in ADMINS
fmt = lambda p: f"{p:.4f}".rstrip("0").rstrip(".") if p is not None else "—"

def fmt_amount(a):
    if a is None:
        return None
    try:
        if a >= 1000:
            s = f"{a:,.2f}"
        elif a >= 1:
            s = f"{a:.4f}".rstrip("0").rstrip(".")
        else:
            s = f"{a:.6f}".rstrip("0").rstrip(".")
        return s
    except:
        return str(a)

def get_settings():
    return state.get("settings", DEFAULT_SETTINGS)

# ── panel ──
BOT_USERNAME = None  # filled in post_init

def set_group_button():
    label = "👥 Change group" if state["group"] else "👥 Set group"
    if BOT_USERNAME:
        return B(label, url=f"https://t.me/{BOT_USERNAME}?startgroup=setgroup")
    return B(label, callback_data="setgroup_help")

def panel():
    a = state["auto"]
    s = get_settings()
    liq_icon = "💧"
    return KB([
        [B("📊 Post prices now", callback_data="post"),
         B(f"{'🟢' if a else '🔴'} Auto: {'ON' if a else 'OFF'}", callback_data="auto")],
        [B("📋 Merchants", callback_data="list"), set_group_button()],
        [B("⚙️ Settings", callback_data="settings"), B("📝 Custom Msg", callback_data="custom_menu")],
        [B(f"{liq_icon} Liquidity: {'ON' if s.get('show_liquidity') else 'OFF'}", callback_data="toggle_liquidity"),
         B(f"🔘 Buttons: {'ON' if s.get('show_buttons') else 'OFF'}", callback_data="toggle_buttons")],
        [B("👁 Preview", callback_data="preview"), B("🔄 Refresh", callback_data="panel")]
    ])

def settings_kb():
    s = get_settings()
    return KB([
        [B(f"💧 Liquidity: {'ON ✅' if s.get('show_liquidity') else 'OFF ❌'}", callback_data="toggle_liquidity"),
         B(f"🔘 Buy/Sell Buttons: {'ON ✅' if s.get('show_buttons') else 'OFF ❌'}", callback_data="toggle_buttons")],
        [B(f"🗑 Auto-delete prev: {'ON ✅' if s.get('auto_delete') else 'OFF ❌'}", callback_data="toggle_autodelete"),
         B(f"⏰ Delete after {s.get('delete_after_hours',24)}h", callback_data="toggle_delete_hours")],
        [B(f"🚪 Del Join/Left msgs: {'ON ✅' if s.get('delete_join_left', True) else 'OFF ❌'}", callback_data="toggle_joinleft")],
        [B("📝 Edit Header", callback_data="edit_header"), B("📝 Edit Body", callback_data="edit_body")],
        [B("📝 Edit Footer", callback_data="edit_footer"), B("🗑 Clear Custom Msg", callback_data="clear_custom")],
        [B("👁 Preview", callback_data="preview"), B("⬅️ Back", callback_data="panel")]
    ])

def custom_menu_kb():
    return KB([
        [B("📝 Edit Header", callback_data="edit_header"), B("📝 Edit Body", callback_data="edit_body")],
        [B("📝 Edit Footer", callback_data="edit_footer"), B("🗑 Clear All Custom", callback_data="clear_custom")],
        [B("👁 Preview", callback_data="preview"), B("⬅️ Back", callback_data="panel")]
    ])

def group_label():
    if not state["group"]: return None
    t = state.get("group_title")
    return f"{t} ({state['group']})" if t else str(state["group"])

def panel_text():
    g = group_label() or "not set — tap 👥 Set group below"
    s = get_settings()
    liq = "ON" if s.get("show_liquidity") else "OFF"
    btns = "ON" if s.get("show_buttons") else "OFF"
    autodel = "ON" if s.get("auto_delete") else "OFF"
    joinleft = "ON" if s.get("delete_join_left", True) else "OFF"
    header = s.get("custom_header") or "(default)"
    body = s.get("custom_body") or "(default)"
    footer = s.get("custom_footer") or "(none)"
    header_short = (header[:60] + "…") if len(header) > 60 else header
    body_short = (body[:60] + "…") if len(body) > 60 else body
    footer_short = (footer[:60] + "…") if len(footer) > 60 else footer
    last_msg = f"Last msg: {state.get('last_msg_id')}" if state.get('last_msg_id') else "No group msg yet"
    return (
        f"🤖 <b>P2P Price Bot</b>\n"
        f"Group: <code>{g}</code>\n"
        f"Merchants: {len(state['merchants'])} · Pair: {ASSET}/{FIAT} · every {INTERVAL}s\n"
        f"💧 Liquidity: <b>{liq}</b> · 🔘 Buttons: <b>{btns}</b> · 🗑 AutoDel: <b>{autodel}</b>\n"
        f"🚪 Del Join/Left msgs: <b>{joinleft}</b>\n"
        f"📝 Header: <code>{header_short}</code>\n"
        f"📝 Body: <code>{body_short}</code>\n"
        f"📝 Footer: <code>{footer_short}</code>\n"
        f"{last_msg}\n\n"
        f"➕ <b>Paste a merchant's public URL here to add it.</b>\n"
        f"Use ⚙️ Settings to toggle options and 📝 Custom Msg to customize the full post (header, body, footer)."
    )

def settings_text():
    s = get_settings()
    liq = "ON ✅" if s.get("show_liquidity") else "OFF ❌"
    btns = "ON ✅" if s.get("show_buttons") else "OFF ❌"
    autodel = "ON ✅" if s.get("auto_delete") else "OFF ❌"
    joinleft = "ON ✅" if s.get("delete_join_left", True) else "OFF ❌"
    del_hours = s.get("delete_after_hours", 24)
    header = s.get("custom_header") or "<i>(default: 📊 P2P {ASSET}/{FIAT})</i>"
    body = s.get("custom_body") or "<i>(default: exchange · merchant with sell/buy lines)</i>"
    footer = s.get("custom_footer") or "<i>(none)</i>"
    return (
        f"⚙️ <b>Settings</b>\n\n"
        f"💧 Show liquidity amount: <b>{liq}</b>\n"
        f"   When ON, shows available amount next to price.\n\n"
        f"🔘 Show Buy/Sell buttons in group: <b>{btns}</b>\n"
        f"   When ON, group message includes Buy/Sell URL buttons.\n\n"
        f"🗑 Auto-delete previous message: <b>{autodel}</b>\n"
        f"   When ON, deletes previous price message on refresh/update.\n\n"
        f"⏰ Auto-delete after: <b>{del_hours}h</b>\n"
        f"   Message will be deleted after {del_hours} hours (0 = never).\n\n"
        f"🚪 Delete Join/Left messages: <b>{joinleft}</b>\n"
        f"   When ON, the bot deletes Telegram's \"user joined the group\" and\n"
        f"   \"user left the group\" service messages in your group.\n"
        f"   ⚠️ Bot must be a group admin with 'Delete messages' permission.\n\n"
        f"📝 Custom Header:\n{header}\n\n"
        f"📝 Custom Body (per merchant):\n{body}\n\n"
        f"📝 Custom Footer:\n{footer}\n\n"
        f"Header/Footer placeholders: <code>{{ASSET}}</code>, <code>{{FIAT}}</code>, <code>{{PAIR}}</code>\n"
        f"Body placeholders: <code>{{ICON}}</code> <code>{{EXCHANGE}}</code> <code>{{NICK}}</code> <code>{{SELL}}</code> <code>{{BUY}}</code> "
        f"<code>{{SELL_AMOUNT}}</code> <code>{{BUY_AMOUNT}}</code> <code>{{LINK}}</code> <code>{{URL}}</code> <code>{{ERROR}}</code> and header ones.\n"
        f"HTML allowed: &lt;b&gt;, &lt;i&gt;, &lt;code&gt;, &lt;a&gt; etc."
    )

def custom_menu_text():
    s = get_settings()
    header = s.get("custom_header") or "<i>(default)</i>"
    body = s.get("custom_body") or "<i>(default)</i>"
    footer = s.get("custom_footer") or "<i>(none)</i>"
    return (
        f"📝 <b>Custom Message</b>\n\n"
        f"Customize the full group post. The <b>Header</b> appears once on top, the <b>Body</b> "
        f"is repeated for every merchant, and the <b>Footer</b> appears once at the bottom.\n\n"
        f"<b>Current Header:</b>\n{header}\n\n"
        f"<b>Current Body (per merchant):</b>\n{body}\n\n"
        f"<b>Current Footer:</b>\n{footer}\n\n"
        f"Tap Edit to change. You can use:\n"
        f"• <code>{{ASSET}}</code> / <code>{{FIAT}}</code> / <code>{{PAIR}}</code>\n"
        f"• Body only: <code>{{ICON}}</code> <code>{{EXCHANGE}}</code> <code>{{NICK}}</code> <code>{{SELL}}</code> <code>{{BUY}}</code> "
        f"<code>{{SELL_AMOUNT}}</code> <code>{{BUY_AMOUNT}}</code> <code>{{LINK}}</code> <code>{{URL}}</code> <code>{{ERROR}}</code>\n"
        f"• HTML formatting, new lines supported\n"
        f"• Send /cancel to abort editing\n\n"
        f"Example header:\n<code>📊 P2P {{ASSET}}/{{FIAT}} - Best Rates 🔥</code>\n"
        f"Example body:\n<code>{{ICON}} {{NICK}} — Sell: {{SELL}} | Buy: {{BUY}} {{FIAT}}</code>\n"
        f"Example footer:\n<code>⚡️ Updated every {INTERVAL}s | Contact @youradmin</code>"
    )

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

# ── delete "X joined / left the group" service messages ──
async def on_join_left(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Auto-delete Telegram's join/leave service messages in the group."""
    if not get_settings().get("delete_join_left", DEFAULT_SETTINGS["delete_join_left"]):
        return
    msg, chat = u.effective_message, u.effective_chat
    if not msg or not chat or chat.type not in ("group", "supergroup"):
        return
    # only in the registered group (if one is set)
    if state.get("group") and chat.id != state["group"]:
        return
    try:
        await msg.delete()
        kind = "joined" if msg.new_chat_members else "left"
        member = msg.new_chat_members[0] if msg.new_chat_members else msg.left_chat_member
        log.info("Deleted '%s the group' service message for %s in %s",
                 kind, getattr(member, "full_name", "?"), chat.id)
    except Exception as e:
        log.warning("Could not delete join/left msg in %s: %s "
                    "(make the bot a group admin with 'Delete messages' permission)", chat.id, e)

# ── custom message helpers ──
def apply_template(text: str) -> str:
    if not text:
        return ""
    return (text
            .replace("{ASSET}", ASSET).replace("{FIAT}", FIAT)
            .replace("{asset}", ASSET.lower()).replace("{fiat}", FIAT.lower())
            .replace("{Asset}", ASSET.title()).replace("{Fiat}", FIAT.title())
            .replace("{PAIR}", f"{ASSET}/{FIAT}").replace("{pair}", f"{ASSET}/{FIAT}"))

def apply_body_template(tpl: str, m: Merchant, r: dict) -> str:
    """Render a custom per-merchant body block with placeholders.
    Single-pass substitution: inserted values are never re-scanned."""
    if not tpl:
        return ""
    nick = m.nickname or m.merchant_id
    link = f'<a href="{m.url}">{nick}</a>' if m.url else nick
    sell_amt = fmt_amount(r.get("sell_amount")) or "—"
    buy_amt = fmt_amount(r.get("buy_amount")) or "—"
    sell, buy = fmt(r.get("sell")), fmt(r.get("buy"))
    err = r.get("error") or ""
    mapping = {
        "ASSET": ASSET, "asset": ASSET.lower(), "Asset": ASSET.title(),
        "FIAT": FIAT, "fiat": FIAT.lower(), "Fiat": FIAT.title(),
        "PAIR": f"{ASSET}/{FIAT}", "pair": f"{ASSET}/{FIAT}",
        "ICON": ICON.get(m.exchange, "💱"),
        "EXCHANGE": m.exchange.title(), "exchange": m.exchange, "Exchange": m.exchange.title(),
        "NICK": nick, "nick": nick, "Nick": (nick[:1].upper() + nick[1:]) if nick else nick,
        "URL": m.url or "", "url": m.url or "",
        "LINK": link, "Link": link,
        "SELL": sell, "Sell": sell, "BUY": buy, "Buy": buy,
        "SELL_AMOUNT": sell_amt, "BUY_AMOUNT": buy_amt,
        "SELL_LIQ": sell_amt, "BUY_LIQ": buy_amt,
        "ERROR": err, "error": err,
    }
    keys = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(r"\{(" + "|".join(re.escape(k) for k in keys) + r")\}")
    return pattern.sub(lambda mm: mapping[mm.group(1)], tpl)

# ── add merchant by pasting URL / handle custom msg input ──
async def on_text(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u) or u.effective_chat.type != "private": return
    txt = u.message.text.strip()

    awaiting = c.user_data.get("awaiting_custom")
    if awaiting in ("header", "body", "footer"):
        if txt.lower() == "/cancel":
            c.user_data.pop("awaiting_custom", None)
            await u.message.reply_text("❌ Cancelled.", reply_markup=panel())
            return
        state["settings"][f"custom_{awaiting}"] = txt
        save()
        c.user_data.pop("awaiting_custom", None)
        await u.message.reply_html(f"✅ Custom {awaiting} saved:\n<code>{txt[:500]}</code>", reply_markup=panel())
        await u.message.reply_html(panel_text(), reply_markup=panel())
        return

    m = parse_url(txt, ASSET, FIAT)
    if not m:
        return await u.message.reply_text("❌ Not a supported merchant URL (Binance / Bybit / OKX / Bitget).   /start")
    msg = await u.message.reply_text("⏳ Checking merchant…")
    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as cl:
        r = await fetch(cl, m)
    state["merchants"][m.key] = asdict(m); save()
    extra = ""
    s = get_settings()
    if s.get("show_liquidity"):
        if r.get("sell_amount") is not None:
            extra += f"\nSell liq: {fmt_amount(r['sell_amount'])} {m.asset}"
        if r.get("buy_amount") is not None:
            extra += f"\nBuy liq: {fmt_amount(r['buy_amount'])} {m.asset}"
    await msg.edit_text(f"✅ Added {ICON[m.exchange]} {m.exchange.title()} · {m.nickname or m.merchant_id}\n"
                        f"Sell: {fmt(r['sell'])} · Buy: {fmt(r['buy'])}{extra}")
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
    s = get_settings()
    custom_header = s.get("custom_header", "").strip()
    if custom_header:
        header_raw = apply_template(custom_header)
        lines = [header_raw, ""]
    else:
        lines = [f"📊 <b>P2P {ASSET}/{FIAT}</b>\n"]

    custom_body = s.get("custom_body", "").strip()
    for m in merchants():
        r = prices.get(m.key)
        if not r:
            continue
        if custom_body:
            block = apply_body_template(custom_body, m, r).strip()
            if block:
                lines.append(block)
            continue
        nick_display = m.nickname or m.merchant_id
        lines.append(f"{ICON[m.exchange]} <b>{m.exchange.title()}</b> · "
                     f"<a href=\"{m.url}\">{nick_display}</a>")
        if r.get("error"):
            lines.append(f"   ⚠️ {r['error']}\n")
            continue
        sell_price = fmt(r.get("sell"))
        buy_price = fmt(r.get("buy"))
        sell_amt = fmt_amount(r.get("sell_amount")) if s.get("show_liquidity") else None
        buy_amt = fmt_amount(r.get("buy_amount")) if s.get("show_liquidity") else None

        sell_line = f"   🔴 Best SELL (you buy): <b>{sell_price}</b>"
        if sell_amt:
            sell_line += f"  💧 {sell_amt} {m.asset}"
        buy_line = f"   🟢 Best BUY  (you sell): <b>{buy_price}</b>"
        if buy_amt:
            buy_line += f"  💧 {buy_amt} {m.asset}"

        lines.append(sell_line)
        lines.append(buy_line + "\n")

    custom_footer = s.get("custom_footer", "").strip()
    if custom_footer:
        lines.append(apply_template(custom_footer))

    return "\n".join(lines).strip()

def report_keyboard(prices):
    s = get_settings()
    if not s.get("show_buttons"):
        return None
    rows = []
    for m in merchants():
        r = prices.get(m.key)
        if not r or not m.url:
            continue
        nick = (m.nickname or m.merchant_id)[:14]
        row = []
        sell = r.get("sell")
        buy = r.get("buy")
        if sell is not None:
            label = f"🔴 SELL {fmt(sell)} {nick}"
            if len(label) > 60:
                label = f"🔴 SELL {fmt(sell)}"
            row.append(B(label, url=m.url))
        if buy is not None:
            label = f"🟢 BUY {fmt(buy)} {nick}"
            if len(label) > 60:
                label = f"🟢 BUY {fmt(buy)}"
            row.append(B(label, url=m.url))
        if row:
            rows.append(row)
    if not rows:
        return None
    return KB(rows)

# ── deletion helpers ──
async def delete_last_group_message(bot):
    """Delete previous price message in group if exists"""
    gid = state.get("group")
    mid = state.get("last_msg_id")
    if not gid or not mid:
        return False
    try:
        await bot.delete_message(chat_id=gid, message_id=mid)
        log.info(f"Deleted previous group message {mid} in {gid}")
        state["last_msg_id"] = None
        state["last_msg_time"] = None
        save()
        return True
    except Exception as e:
        # message may already be deleted or bot not admin
        log.debug(f"Could not delete msg {mid}: {e}")
        # if message not found, clear state to avoid repeated attempts
        if "not found" in str(e).lower() or "message to delete not found" in str(e).lower() or "BadRequest" in str(type(e)):
            state["last_msg_id"] = None
            state["last_msg_time"] = None
            save()
        return False

async def post(bot, force=False):
    if not state["group"] or not state["merchants"]: return False
    prices = await get_prices()
    s = get_settings()
    if s.get("show_liquidity"):
        snap = {k: [v.get("sell"), v.get("buy"), v.get("sell_amount"), v.get("buy_amount")] for k, v in prices.items()}
    else:
        snap = {k: [v.get("sell"), v.get("buy")] for k, v in prices.items()}
    snap["_header"] = s.get("custom_header","")
    snap["_body"] = s.get("custom_body","")
    snap["_footer"] = s.get("custom_footer","")
    snap["_liq"] = s.get("show_liquidity")
    snap["_btn"] = s.get("show_buttons")
    if not force and snap == state["last"]: return False
    state["last"] = snap; save()

    # Delete previous message if auto_delete enabled (refresh button or update time)
    if s.get("auto_delete", True):
        await delete_last_group_message(bot)

    text = report(prices)
    kb = report_keyboard(prices)
    try:
        sent = await bot.send_message(state["group"], text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb)
        # store new message id and time
        state["last_msg_id"] = sent.message_id
        state["last_msg_time"] = int(time.time())
        save()
        log.info(f"Posted new price message {sent.message_id} to group {state['group']}")
    except Exception as e:
        log.warning(f"Failed to post to group: {e}")
        return False
    return True

async def job(c: ContextTypes.DEFAULT_TYPE):
    if state["auto"]:
        try: await post(c.bot)
        except Exception as e: logging.warning("auto post failed: %s", e)

async def cleanup_job(c: ContextTypes.DEFAULT_TYPE):
    """Delete group message after delete_after_hours (default 24h)"""
    s = get_settings()
    hours = s.get("delete_after_hours", 24)
    if hours <= 0:
        return  # disabled
    last_time = state.get("last_msg_time")
    if not last_time or not state.get("last_msg_id") or not state.get("group"):
        return
    now = int(time.time())
    if now - last_time >= hours * 3600:
        log.info(f"Message {state['last_msg_id']} is older than {hours}h, auto-deleting")
        try:
            await c.bot.delete_message(chat_id=state["group"], message_id=state["last_msg_id"])
            state["last_msg_id"] = None
            state["last_msg_time"] = None
            save()
        except Exception as e:
            log.debug(f"Cleanup delete failed: {e}")
            # clear if not found
            if "not found" in str(e).lower():
                state["last_msg_id"] = None
                state["last_msg_time"] = None
                save()

# ── buttons ──
def list_kb():
    rows = [[B(f"❌ {ICON[m.exchange]} {m.exchange.title()} · {m.nickname or m.merchant_id}",
               callback_data=f"del:{m.key}")] for m in merchants()]
    return KB(rows + [[B("⬅️ Back", callback_data="panel")]])

async def on_button(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    if not is_admin(u): return await q.answer()
    d = q.data

    if d == "post":
        ok = await post(c.bot, force=True)
        await q.answer("✅ Posted!" if ok else "⚠️ Set group (/setgroup) and add merchants first", show_alert=not ok)

    elif d == "auto":
        state["auto"] = not state["auto"]; save(); await q.answer(f"Auto {'ON' if state['auto'] else 'OFF'}")

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
        return await q.edit_message_text("📋 <b>Merchants</b> — tap to remove" if state["merchants"]
                                         else "📋 No merchants yet.",
                                         parse_mode="HTML", reply_markup=list_kb())

    elif d == "settings":
        await q.answer()
        return await q.edit_message_text(settings_text(), parse_mode="HTML", reply_markup=settings_kb())

    elif d == "custom_menu":
        await q.answer()
        return await q.edit_message_text(custom_menu_text(), parse_mode="HTML", reply_markup=custom_menu_kb())

    elif d == "toggle_liquidity":
        state["settings"]["show_liquidity"] = not state["settings"].get("show_liquidity", False)
        save()
        await q.answer(f"Liquidity {'ON' if state['settings']['show_liquidity'] else 'OFF'}")
        try:
            if "Settings" in q.message.text_html or "Settings" in (q.message.text or ""):
                return await q.edit_message_text(settings_text(), parse_mode="HTML", reply_markup=settings_kb())
        except:
            pass

    elif d == "toggle_buttons":
        state["settings"]["show_buttons"] = not state["settings"].get("show_buttons", True)
        save()
        await q.answer(f"Buttons {'ON' if state['settings']['show_buttons'] else 'OFF'}")
        try:
            if "Settings" in (q.message.text or "") or "⚙️" in (q.message.text or ""):
                return await q.edit_message_text(settings_text(), parse_mode="HTML", reply_markup=settings_kb())
        except:
            pass

    elif d == "toggle_autodelete":
        state["settings"]["auto_delete"] = not state["settings"].get("auto_delete", True)
        save()
        await q.answer(f"Auto-delete {'ON' if state['settings']['auto_delete'] else 'OFF'}")
        try:
            return await q.edit_message_text(settings_text(), parse_mode="HTML", reply_markup=settings_kb())
        except:
            pass

    elif d == "toggle_delete_hours":
        # cycle through 0, 6, 12, 24, 48
        options = [0, 6, 12, 24, 48]
        cur = state["settings"].get("delete_after_hours", 24)
        try:
            idx = options.index(cur)
            nxt = options[(idx + 1) % len(options)]
        except:
            nxt = 24
        state["settings"]["delete_after_hours"] = nxt
        save()
        await q.answer(f"Delete after {nxt}h" if nxt else "Never auto-delete")
        try:
            return await q.edit_message_text(settings_text(), parse_mode="HTML", reply_markup=settings_kb())
        except:
            pass

    elif d == "edit_header":
        c.user_data["awaiting_custom"] = "header"
        await q.answer()
        return await q.edit_message_text(
            "📝 <b>Send new custom HEADER now</b>\n\n"
            "You can use:\n"
            f"• <code>{{ASSET}}</code> = {ASSET}\n"
            f"• <code>{{FIAT}}</code> = {FIAT}\n"
            "• HTML tags like &lt;b&gt;bold&lt;/b&gt;\n\n"
            "Current:\n"
            f"<code>{state['settings'].get('custom_header') or '(default)'}</code>\n\n"
            "Send the new header text, or /cancel to abort.",
            parse_mode="HTML",
            reply_markup=KB([[B("❌ Cancel", callback_data="cancel_edit")]])
        )

    elif d == "edit_body":
        c.user_data["awaiting_custom"] = "body"
        await q.answer()
        return await q.edit_message_text(
            "📝 <b>Send new custom BODY now</b>\n\n"
            "The body is repeated once per merchant in the group post.\n\n"
            "Placeholders:\n"
            "• <code>{ICON}</code> <code>{EXCHANGE}</code> <code>{NICK}</code>\n"
            "• <code>{SELL}</code> <code>{BUY}</code> — best prices\n"
            "• <code>{SELL_AMOUNT}</code> <code>{BUY_AMOUNT}</code> — liquidity\n"
            "• <code>{LINK}</code> — clickable merchant name\n"
            "• <code>{URL}</code> — merchant profile link\n"
            "• <code>{ERROR}</code> — fetch error (if any)\n"
            f"• <code>{{ASSET}}</code> = {ASSET} · <code>{{FIAT}}</code> = {FIAT} · <code>{{PAIR}}</code> = {ASSET}/{FIAT}\n"
            "• HTML tags and new lines are supported\n\n"
            "Example (default look):\n"
            "<code>{ICON} &lt;b&gt;{EXCHANGE}&lt;/b&gt; · {LINK}\n"
            "🔴 Sell: &lt;b&gt;{SELL}&lt;/b&gt; 💧 {SELL_AMOUNT} {ASSET}\n"
            "🟢 Buy: &lt;b&gt;{BUY}&lt;/b&gt; 💧 {BUY_AMOUNT} {ASSET}</code>\n\n"
            "Current:\n"
            f"<code>{state['settings'].get('custom_body') or '(default)'}</code>\n\n"
            "Send the new body text, or /cancel to abort.",
            parse_mode="HTML",
            reply_markup=KB([[B("❌ Cancel", callback_data="cancel_edit")]])
        )

    elif d == "edit_footer":
        c.user_data["awaiting_custom"] = "footer"
        await q.answer()
        return await q.edit_message_text(
            "📝 <b>Send new custom FOOTER now</b>\n\n"
            "You can use:\n"
            f"• <code>{{ASSET}}</code> = {ASSET}\n"
            f"• <code>{{FIAT}}</code> = {FIAT}\n"
            "• HTML tags\n\n"
            "Current:\n"
            f"<code>{state['settings'].get('custom_footer') or '(none)'}</code>\n\n"
            "Send the new footer text, or /cancel to abort.",
            parse_mode="HTML",
            reply_markup=KB([[B("❌ Cancel", callback_data="cancel_edit")]])
        )

    elif d == "toggle_joinleft":
        state["settings"]["delete_join_left"] = not state["settings"].get("delete_join_left", True)
        save()
        await q.answer(f"Delete join/left msgs {'ON' if state['settings']['delete_join_left'] else 'OFF'}")
        try:
            return await q.edit_message_text(settings_text(), parse_mode="HTML", reply_markup=settings_kb())
        except:
            pass

    elif d == "clear_custom":
        state["settings"]["custom_header"] = ""
        state["settings"]["custom_body"] = ""
        state["settings"]["custom_footer"] = ""
        save()
        await q.answer("🗑 Custom message cleared")
        return await q.edit_message_text(custom_menu_text(), parse_mode="HTML", reply_markup=custom_menu_kb())

    elif d == "cancel_edit":
        c.user_data.pop("awaiting_custom", None)
        await q.answer("Cancelled")
        return await q.edit_message_text(panel_text(), parse_mode="HTML", reply_markup=panel())

    elif d == "preview":
        await q.answer("Generating preview…")
        if state["merchants"]:
            prices = await get_prices()
        else:
            prices = {}
        text = report(prices) if prices else (
            f"{apply_template(state['settings'].get('custom_header')) or f'📊 P2P {ASSET}/{FIAT}'}\n\n"
            f"<i>No merchants yet. Add one to see prices.</i>\n\n"
            f"{apply_template(state['settings'].get('custom_footer')) or ''}"
        )
        kb = report_keyboard(prices) if prices else None
        try:
            await c.bot.send_message(q.message.chat_id, f"👁 <b>Preview - how it will look in group:</b>\n\n{text}",
                                     parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb)
        except Exception as e:
            await c.bot.send_message(q.message.chat_id, f"Preview error: {e}\n\n{text[:3000]}", parse_mode="HTML")
        return

    elif d == "panel":
        await q.answer()

    else:
        await q.answer()
        return

    try: await q.edit_message_text(panel_text(), parse_mode="HTML", reply_markup=panel())
    except Exception: pass

async def cancel_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u): return
    if c.user_data.get("awaiting_custom"):
        c.user_data.pop("awaiting_custom")
        await u.message.reply_text("❌ Editing cancelled.", reply_markup=panel())
    else:
        await u.message.reply_text("Nothing to cancel.", reply_markup=panel())

async def preview_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u) or u.effective_chat.type != "private": return
    if state["merchants"]:
        prices = await get_prices()
        text = report(prices)
        kb = report_keyboard(prices)
    else:
        text = f"{apply_template(state['settings'].get('custom_header')) or f'📊 P2P {ASSET}/{FIAT}'}\n\n<i>No merchants yet.</i>"
        kb = None
    await u.message.reply_html(text, reply_markup=kb, disable_web_page_preview=True)

async def error_handler(update, context):
    log.warning("Update %s caused error %s", update, context.error)

# ── run ──
def main():
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
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("preview", preview_cmd))
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS
                                   | filters.StatusUpdate.LEFT_CHAT_MEMBER, on_join_left))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(error_handler)
    app.job_queue.run_repeating(job, interval=INTERVAL, first=5)
    # cleanup job: check every 10 minutes if message older than 24h
    app.job_queue.run_repeating(cleanup_job, interval=600, first=60)
    print(f"🚀 Bot running · {ASSET}/{FIAT} · every {INTERVAL}s · Ctrl+C to stop")
    print(f"   Admins: {', '.join(map(str, ADMINS))} · Group: {state['group'] or 'not set'} · Merchants: {len(state['merchants'])}")
    if not state["group"]:
        print("   → Open the bot in Telegram, /start, tap 👥 Set group")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
