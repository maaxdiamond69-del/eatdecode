from datetime import datetime, timezone
import asyncio
import json
import os

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from eat_core import get_eat_details, normalize_eat_token

# ==========================
# CONFIG
# ==========================
# Paste bot token here (or set TELEGRAM_BOT_TOKEN / telegram_token.txt)
BOT_TOKEN = "8549249652:AAFIVNG5iT33XNp6NH8PqLTOc2vfu2UnXnw"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
EAT_FILE = os.path.join(DATA_DIR, "eat.json")
ACCESS_FILE = os.path.join(DATA_DIR, "access.json")


def _load_bot_token() -> str:
    env = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if env:
        return env
    if BOT_TOKEN and "paste" not in BOT_TOKEN.lower():
        return BOT_TOKEN.strip()
    path = os.path.join(BASE_DIR, "telegram_token.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    return ""


# ==========================
# SAVE HELPERS
# ==========================

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _load_list(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_list(path: str, items: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def save_eat_token(update: Update, eat_token: str) -> None:
    user = update.effective_user
    items = _load_list(EAT_FILE)
    items.append(
        {
            "eat_token": eat_token,
            "user_id": user.id if user else None,
            "username": user.username if user else None,
            "time": _now(),
        }
    )
    _save_list(EAT_FILE, items)


def save_access_result(update: Update, eat_token: str, result: dict) -> None:
    user = update.effective_user
    items = _load_list(ACCESS_FILE)
    items.append(
        {
            "access_token": str(result.get("access_token", "")),
            "account_id": str(result.get("account_id", "")),
            "eat_token": eat_token,
            "user_id": user.id if user else None,
            "username": user.username if user else None,
            "time": _now(),
        }
    )
    _save_list(ACCESS_FILE, items)


# ==========================
# EXTRACT (same eat_core flow)
# ==========================

async def extract_details(token: str) -> dict:
    # Run sync API flow off the event loop
    return await asyncio.to_thread(get_eat_details, token)


def format_result(data: dict) -> str:
    payload = {
        "access_token": str(data.get("access_token", "")),
        "account_id": str(data.get("account_id", "")),
    }
    pretty = json.dumps(payload, indent=2, ensure_ascii=False)
    return (
        "🟢 <b>Connected to System</b>\n\n"
        "✅ Token Verified Successfully\n\n"
        "<b>Extracted data</b>\n"
        f"<pre>{pretty}</pre>\n\n"
        f"<b>access_token</b>\n<code>{payload['access_token']}</code>\n\n"
        f"<b>account_id</b>\n<code>{payload['account_id']}</code>"
    )


async def send_json_file(update: Update, path: str, caption: str) -> None:
    if not os.path.exists(path) or os.path.getsize(path) == 0 or not _load_list(path):
        await update.message.reply_text(
            f"No data yet for <b>{os.path.basename(path)}</b>.",
            parse_mode="HTML",
        )
        return
    with open(path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=os.path.basename(path),
            caption=caption,
        )


# ==========================
# COMMANDS
# ==========================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>EatDetails Bot</b>\n\n"
        "Send an EAT token or reward link like:\n"
        "<code>https://reward.ff.garena.com/pt?access_token=...</code>\n\n"
        "Returns only <code>access_token</code> + <code>account_id</code>.\n\n"
        "<b>Commands</b>\n"
        "/eat — send saved EAT tokens file\n"
        "/access — send saved access tokens file\n"
        "/file — send access tokens file",
        parse_mode="HTML",
    )


async def cmd_eat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_json_file(
        update,
        EAT_FILE,
        "Saved EAT tokens (what customers sent)",
    )


async def cmd_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_json_file(
        update,
        ACCESS_FILE,
        "Saved access tokens (extract responses)",
    )


async def cmd_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_json_file(
        update,
        ACCESS_FILE,
        "Saved access tokens (extract responses)",
    )


# ==========================
# HANDLE MESSAGE
# ==========================

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    raw = update.message.text.strip()
    token = normalize_eat_token(raw)

    if not token:
        await update.message.reply_text(
            "❌ Please send a valid EAT token or reward.ff.garena.com link."
        )
        return

    # Always save what the customer sent
    save_eat_token(update, token)

    waiting = await update.message.reply_text("🔄 Connecting to System...")

    try:
        result = await extract_details(token)
        save_access_result(update, token, result)
        text = format_result(result)
    except Exception:
        text = (
            "⚠️ <b>System Busy</b>\n\n"
            "🔄 API not responding.\n"
            "Please try again later."
        )

    await waiting.edit_text(text, parse_mode="HTML")


# ==========================
# MAIN
# ==========================

def main():
    token = _load_bot_token()
    if not token:
        raise SystemExit(
            "Set TELEGRAM_BOT_TOKEN, or put token in telegram_token.txt, "
            "or paste it in BOT_TOKEN."
        )

    os.makedirs(DATA_DIR, exist_ok=True)

    # Bypass SSL issues on some Windows / proxy networks
    import ssl
    import httpx
    from telegram.request import HTTPXRequest

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        http_version="1.1",
        httpx_kwargs={"verify": False},
    )

    app = (
        ApplicationBuilder()
        .token(token)
        .request(request)
        .get_updates_request(request)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("eat", cmd_eat))
    app.add_handler(CommandHandler("access", cmd_access))
    app.add_handler(CommandHandler("file", cmd_file))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle,
        )
    )

    print("Bot Started...", flush=True)
    print(f"Token OK: {token[:10]}...", flush=True)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
