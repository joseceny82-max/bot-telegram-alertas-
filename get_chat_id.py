"""Muestra los chats/canales donde está tu bot de Telegram (para rellenar TELEGRAM_CHAT_ID).
Antes: añade el bot como admin a tu canal y publica cualquier mensaje en él."""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()
API = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org")


def find_chats(token: str) -> dict[int, str]:
    r = requests.get(f"{API}/bot{token}/getUpdates", timeout=15).json()
    if not r.get("ok"):
        raise SystemExit(f"Telegram rechazó el token: {r.get('description')}")
    chats = {}
    for u in r["result"]:
        for key in ("message", "channel_post", "my_chat_member", "edited_channel_post"):
            chat = (u.get(key) or {}).get("chat")
            if chat:
                chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name", "")
    return chats


if __name__ == "__main__":
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("Pon TELEGRAM_BOT_TOKEN en .env primero")
    chats = find_chats(token)
    if not chats:
        sys.exit("Sin resultados: añade el bot como admin al canal, publica un mensaje y repite.")
    for cid, name in chats.items():
        print(f"{cid}\t{name}")
