"""Comprueba el .env sin mostrar los secretos: formato + conexión real a Discord y Telegram."""
import os
import re

import requests
from dotenv import dotenv_values

HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
DISCORD_TOKEN_RE = re.compile(r"^[\w-]{20,}\.[\w-]{4,}\.[\w-]{20,}$")
TG_TOKEN_RE = re.compile(r"^\d{6,}:[\w-]{30,}$")


def check_format(env: dict) -> list[str]:
    errs = []
    d = (env.get("DISCORD_TOKEN") or "").strip()
    if not d:
        errs.append("DISCORD_TOKEN vacío")
    elif HEX64.match(d):
        errs.append("DISCORD_TOKEN es la PUBLIC KEY: usa el token de la sección Bot (Reset Token)")
    elif d.isdigit():
        errs.append("DISCORD_TOKEN es un ID numérico (Application ID): usa el token de la sección Bot")
    elif not DISCORD_TOKEN_RE.match(d):
        errs.append("DISCORD_TOKEN no tiene formato de token de bot (3 partes separadas por puntos)")
    t = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not t:
        errs.append("TELEGRAM_BOT_TOKEN vacío")
    elif not TG_TOKEN_RE.match(t):
        errs.append("TELEGRAM_BOT_TOKEN no tiene formato 123456789:ABC...")
    c = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    if not c:
        errs.append("TELEGRAM_CHAT_ID vacío (ejecuta chat_id.bat)")
    elif not re.match(r"^-?\d+$", c):
        errs.append("TELEGRAM_CHAT_ID debe ser un número (canales: -100...)")
    ch = env.get("DISCORD_CHANNEL_IDS") or ""
    if not all(x.strip().isdigit() for x in ch.split(",") if x.strip()) or not ch.strip():
        errs.append("DISCORD_CHANNEL_IDS debe ser lista de números separados por comas")
    return errs


def check_live(env: dict) -> list[str]:
    out = []
    r = requests.get("https://discord.com/api/v10/users/@me",
                     headers={"Authorization": f"Bot {env['DISCORD_TOKEN'].strip()}"}, timeout=15)
    out.append(f"Discord: OK, bot '{r.json().get('username')}'" if r.ok else f"Discord: ERROR {r.status_code} (token inválido)")
    r = requests.get(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN'].strip()}/getMe", timeout=15).json()
    out.append(f"Telegram: OK, bot @{r['result']['username']}" if r.get("ok") else f"Telegram: ERROR {r.get('description')}")
    return out


if __name__ == "__main__":
    env = dotenv_values(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    errs = check_format(env)
    for e in errs:
        print("X", e)
    if not any(k in e for e in errs for k in ("DISCORD_TOKEN", "TELEGRAM_BOT_TOKEN")):
        for line in check_live(env):
            print("->", line)
    if not errs:
        print("Formato del .env correcto")
