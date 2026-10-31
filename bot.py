"""Puente Discord -> Telegram: reenvía los mensajes (texto, embeds e imágenes)
de uno o varios canales de Discord a un chat/canal de Telegram."""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
from collections import deque
import re

import aiohttp
from aiohttp import web
import discord
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("alerts")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CHANNEL_IDS = {int(c) for c in os.getenv("DISCORD_CHANNEL_IDS", "").split(",") if c.strip()}


def parse_routes(raw: str, default_chat: str, channels: set[int]) -> dict[int, list[str]]:
    """ROUTES="canal:chat,canal:chat2,..." -> {canal: [chats]}. Sin ROUTES: todos los canales al chat por defecto."""
    routes: dict[int, list[str]] = {}
    for item in (raw or "").split(","):
        if ":" in item:
            cid, chat = item.split(":", 1)
            routes.setdefault(int(cid.strip()), []).append(chat.strip())
    if not routes:
        routes = {c: [default_chat] for c in channels}
    return routes


WEBHOOK_URLS = [u.strip() for u in os.getenv("WEBHOOK_URLS", "").split(",") if u.strip()]
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

API_TOKEN = os.getenv("API_TOKEN", "")
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", "8080")))
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "")
BACKFILL = int(os.getenv("BACKFILL", "50"))

ROUTES = parse_routes(os.getenv("ROUTES", ""), TG_CHAT_ID, CHANNEL_IDS)
TG_MAX = 4096
TG_CAPTION_MAX = 1024


def esc(text: str | None) -> str:
    return html.escape(text or "", quote=False)


MD_RULES = [
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)"), r'<a href="\2">\1</a>'),
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"<b>\1</b>"),
    (re.compile(r"__(.+?)__", re.S), r"<u>\1</u>"),
    (re.compile(r"~~(.+?)~~", re.S), r"<s>\1</s>"),
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
]


def md(text: str | None) -> str:
    """Escapa HTML y convierte el markdown básico de Discord al HTML de Telegram."""
    out = esc(text)
    for rx, rep in MD_RULES:
        out = rx.sub(rep, out)
    return out


def format_message(author: str, channel: str, content: str, embeds: list[dict], jump_url: str) -> str:
    """Construye el texto HTML para Telegram a partir de un mensaje de Discord."""
    icon = "✅" if "complet" in channel.lower() else "🛒"
    parts = [f"{icon} <b>{esc(channel)}</b> · {esc(author)}"]
    if content:
        parts.append(md(content))
    for e in embeds:
        a = (e.get("author") or {}).get("name")
        if a and esc(a) not in parts[-1]:
            parts.append(f"<i>{md(a)}</i>")
        if e.get("title"):
            title = md(e["title"])
            parts.append(f'<b><a href="{esc(e["url"])}">{title}</a></b>' if e.get("url") else f"<b>{title}</b>")
        if e.get("description"):
            parts.append(md(e["description"]))
        for f in e.get("fields", []):
            parts.append(f"<b>{md(f.get('name'))}:</b> {md(f.get('value'))}")
        foot = (e.get("footer") or {}).get("text")
        if foot:
            parts.append(f"<i>{md(foot)}</i>")
    parts.append(f'<a href="{esc(jump_url)}">Ver en Discord</a>')
    return "\n".join(parts)


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def first_image(attachments: list[dict], embeds: list[dict]) -> str | None:
    for a in attachments:
        if (a.get("content_type") or "").startswith("image/"):
            return a["url"]
    for e in embeds:
        img = (e.get("image") or {}).get("url") or (e.get("thumbnail") or {}).get("url")
        if img:
            return img
    return None


FIELD_KEYS = {"partido": "partido", "worker": "worker", "entradas": "entradas", "total": "total",
              "sectores": "sectores", "página del evento": "evento_url", "pagina del evento": "evento_url", "url": "url"}
LINK_RX = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def plain(text: str | None) -> str:
    """Quita el markdown de Discord: **negrita**, __, ~~, `code` y [texto](url) -> url."""
    t = LINK_RX.sub(r"\2", html.unescape(text or ""))
    for mark in ("**", "__", "~~", "`"):
        t = t.replace(mark, "")
    return t.strip()


def field_key(name: str) -> str:
    """'💰 Total' -> 'total' (quita emojis/símbolos del principio)."""
    return re.sub(r"^[^\w]+", "", plain(name), flags=re.U).strip().lower()


SEAT_RX = re.compile(r"Fila\s+(\S+)\s*·\s*Asiento\s+(\S+)\s*[—-]\s*([\d.,]+)")
NUM_RX = re.compile(r"\d+(?:[.,]\d+)?")


def to_float(text: str) -> float | None:
    m = NUM_RX.search(text or "")
    return float(m.group().replace(",", ".")) if m else None


def build_event(section: str | None, channel: str, channel_id: int, message_id: int, url: str,
                timestamp: str, author: str, content: str, embeds: list[dict], image: str | None) -> dict:
    """Evento JSON estructurado para el panel de la app."""
    e = embeds[0] if embeds else {}
    fields = {field_key(f.get("name", "")): plain(f.get("value")) for f in e.get("fields", [])}
    data = {FIELD_KEYS[k]: v for k, v in fields.items() if k in FIELD_KEYS}
    # Asientos: campos "📍 Sector X" con líneas "Fila N · Asiento M — precio"
    seats = []
    for f in e.get("fields", []):
        name = re.sub(r"^[^\w]+", "", plain(f.get("name")), flags=re.U).strip()
        if name.lower().startswith("sector "):
            for fila, asiento, precio in SEAT_RX.findall(plain(f.get("value"))):
                seats.append({"sector": name[7:], "fila": fila, "asiento": asiento, "precio_eur": to_float(precio)})
    if seats:
        data["asientos"] = seats
        data.setdefault("sectores", ", ".join(dict.fromkeys(x["sector"] for x in seats)))
    # Resumen del content: "✅ Compra completada · PARTIDO · 2 entradas · 194.50 €"
    segs = [x.strip() for x in plain(content).split(" · ")]
    if len(segs) >= 2 and "partido" not in data and not re.search(r"\d+\s+entradas|€", segs[1]):
        data["partido"] = segs[1]
    m = re.search(r"(\d+)\s+entradas", " ".join(segs[1:]) + " " + data.get("total", ""))
    if isinstance(data.get("entradas"), str) and data["entradas"].isdigit():
        data["entradas"] = int(data["entradas"])
    elif m:
        data["entradas"] = int(m.group(1))
    elif seats:
        data["entradas"] = len(seats)
    if "total" not in data:
        tot = next((x for x in segs[1:] if "€" in x), None)
        if tot:
            data["total"] = tot
    if "total" in data:
        data["total_eur"] = to_float(data["total"])
    return {
        "event": "compra_completada" if "complet" in channel.lower() else "carrito",
        "section": section, "channel": channel, "channel_id": str(channel_id),
        "message_id": str(message_id), "message_url": url, "timestamp": timestamp,
        "author": author, "content": plain(content), "title": plain(e.get("title")),
        "description": plain(e.get("description")), "fields": fields,
        "footer": plain((e.get("footer") or {}).get("text")), "image": image, "data": data,
    }


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class Webhook:
    """POST del evento JSON a la(s) URL(s) de la app, con firma HMAC opcional y reintentos."""
    def __init__(self, urls: list[str], secret: str = ""):
        self.urls, self.secret = urls, secret
        self.session: aiohttp.ClientSession | None = None

    async def send(self, event: dict, retries: int = 3) -> list[bool]:
        if not self.urls:
            return []
        self.session = self.session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        body = json.dumps(event, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", "X-Event-Type": event["event"]}
        if self.secret:
            headers["X-Signature-256"] = sign(body, self.secret)
        results = []
        for url in self.urls:
            ok = False
            for attempt in range(retries):
                try:
                    async with self.session.post(url, data=body, headers=headers) as r:
                        ok = 200 <= r.status < 300
                        if ok or r.status < 500:
                            if not ok:
                                log.error("Webhook respondió %s", r.status)
                            break
                except Exception:  # Las URL y excepciones pueden contener credenciales.
                    log.warning("Webhook intento %s falló", attempt + 1)
                await asyncio.sleep(2 ** attempt)
            results.append(ok)
        return results

    async def close(self):
        if self.session:
            await self.session.close()


class Store:
    """Últimas alertas en memoria (se rellena al arrancar leyendo el historial de Discord)."""
    def __init__(self, size: int = 1000):
        self.items: deque[dict] = deque(maxlen=size)
        self.ids: set[str] = set()
        self.subscribers: set[asyncio.Queue] = set()

    def add(self, ev: dict) -> bool:
        if ev["message_id"] in self.ids:
            return False
        if len(self.items) == self.items.maxlen:
            self.ids.discard(self.items[0]["message_id"])
        self.items.append(ev)
        self.ids.add(ev["message_id"])
        for q in list(self.subscribers):
            q.put_nowait(ev)
        return True

    def query(self, event: str | None = None, section: str | None = None,
              since: str | None = None, limit: int = 50) -> list[dict]:
        out = [e for e in self.items
               if (not event or e["event"] == event)
               and (not section or (e["section"] or "").lower() == section.lower())
               and (not since or e["timestamp"] > since)]
        out.sort(key=lambda e: e["timestamp"], reverse=True)
        return out[:max(1, min(limit, 500))]


def make_api(store: Store, token: str = "", cors: str = "", ping: float = 25) -> web.Application:
    """API HTTP para el panel: /health, /api/alerts, /api/alerts/stream (SSE)."""

    if not token or not token.strip():
        raise ValueError("API_TOKEN es obligatorio")

    @web.middleware
    async def mw(request, handler):
        if request.method == "OPTIONS":
            resp = web.Response()
        else:
            if request.path.startswith("/api/"):
                auth = request.headers.get("Authorization", "")
                given = auth[7:].strip() if auth.startswith("Bearer ") else ""
                if not hmac.compare_digest(given, token):
                    resp = web.json_response({"error": "unauthorized"}, status=401)
                    resp.headers["Access-Control-Allow-Origin"] = cors
                    return resp
            resp = await handler(request)
        if not resp.prepared:
            resp.headers["Access-Control-Allow-Origin"] = cors
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        return resp

    async def health(_):
        return web.json_response({"ok": True, "alerts": len(store.items)})

    async def alerts(request):
        q = request.query
        try:
            limit = int(q.get("limit", 50))
        except ValueError:
            return web.json_response({"error": "limit debe ser un número"}, status=400)
        if q.get("type") and q["type"] not in ("carrito", "compra_completada"):
            return web.json_response({"error": "type debe ser carrito o compra_completada"}, status=400)
        items = store.query(q.get("type"), q.get("section"), q.get("since"), limit)
        return web.json_response({"count": len(items), "alerts": items})

    async def stream(request):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                                           "Access-Control-Allow-Origin": cors})
        await resp.prepare(request)
        q: asyncio.Queue = asyncio.Queue()
        store.subscribers.add(q)
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), ping)
                    await resp.write(f"event: alert\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                except asyncio.TimeoutError:
                    await resp.write(b": ping\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            store.subscribers.discard(q)
        return resp

    app = web.Application(middlewares=[mw])
    app.router.add_get("/health", health)
    app.router.add_get("/api/alerts", alerts)
    app.router.add_get("/api/alerts/stream", stream)
    async def preflight(_):
        return web.Response()

    app.router.add_route("OPTIONS", "/{tail:.*}", preflight)
    return app


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self.session: aiohttp.ClientSession | None = None

    async def _call(self, method: str, payload: dict, retries: int = 3) -> dict:
        self.session = self.session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        for attempt in range(retries):
            async with self.session.post(f"{self.base}/{method}", json=payload) as r:
                data = await r.json()
            if data.get("ok"):
                return data
            wait = (data.get("parameters") or {}).get("retry_after")
            if r.status == 429 and wait:
                await asyncio.sleep(wait)
                continue
            log.error("Telegram %s falló (%s): %s", method, r.status, data.get("description"))
            return data
        return {"ok": False}

    async def send(self, text: str, image: str | None, chat_id: str | None = None) -> bool:
        base = {"chat_id": chat_id or self.chat_id, "parse_mode": "HTML"}
        if image and len(text) <= TG_CAPTION_MAX:
            if (await self._call("sendPhoto", {**base, "photo": image, "caption": text})).get("ok"):
                return True
        return bool((await self._call("sendMessage", {**base, "text": truncate(text, TG_MAX),
                                                       "disable_web_page_preview": image is None})).get("ok"))

    async def close(self):
        if self.session:
            await self.session.close()


class Bridge(discord.Client):
    def __init__(self, tg: Telegram, webhook: "Webhook | None" = None):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tg = tg
        self.webhook = webhook or Webhook([])
        self.store = Store()
        self._backfilled = False
        self._runner: web.AppRunner | None = None

    async def setup_hook(self):
        self._runner = web.AppRunner(make_api(self.store, API_TOKEN, CORS_ORIGIN))
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", API_PORT).start()
        log.info("API escuchando en el puerto %s (token %s)", API_PORT, "activado" if API_TOKEN else "DESACTIVADO")

    def to_event(self, m: discord.Message) -> dict:
        embeds = [e.to_dict() for e in m.embeds]
        atts = [{"url": a.url, "content_type": a.content_type} for a in m.attachments]
        cat = getattr(getattr(m.channel, "category", None), "name", None)
        return build_event(cat, m.channel.name, m.channel.id, m.id, m.jump_url, m.created_at.isoformat(),
                           m.author.display_name, m.content, embeds, first_image(atts, embeds))

    async def backfill(self):
        n = 0
        for cid in ROUTES:
            ch = self.get_channel(cid)
            if ch:
                async for m in ch.history(limit=BACKFILL, oldest_first=False):
                    n += self.store.add(self.to_event(m))
        log.info("Historial cargado en la API: %s alertas", n)

    async def on_ready(self):
        log.info("Conectado como %s; rutas canal->chat %s", self.user, ROUTES)
        for cid in ROUTES:
            if not self.get_channel(cid):
                log.warning("Canal %s no visible: ¿el bot está en el servidor y tiene permiso de lectura?", cid)
        if not self._backfilled:
            self._backfilled = True
            await self.backfill()

    async def on_message(self, m: discord.Message):
        if m.channel.id not in ROUTES or m.author.id == self.user.id:
            return
        embeds = [e.to_dict() for e in m.embeds]
        atts = [{"url": a.url, "content_type": a.content_type} for a in m.attachments]
        cat = getattr(getattr(m.channel, "category", None), "name", None)
        label = f"{cat} · {m.channel.name}" if cat else getattr(m.channel, "name", "canal")
        text = format_message(m.author.display_name, label,
                              m.content, embeds, m.jump_url)
        image = first_image(atts, embeds)
        for chat in ROUTES[m.channel.id]:
            ok = await self.tg.send(text, image, chat)
            log.info("Reenviado %s (%s) -> Telegram %s: %s", m.id, label, chat, "OK" if ok else "ERROR")
        event = self.to_event(m)
        self.store.add(event)
        if self.webhook.urls:
            res = await self.webhook.send(event)
            log.info("Webhook %s (%s): %s", m.id, event["event"], ["OK" if r else "ERROR" for r in res])

    async def close(self):
        await self.tg.close()
        await self.webhook.close()
        if self._runner:
            await self._runner.cleanup()
        await super().close()


def main():
    missing = [k for k, v in {"DISCORD_TOKEN": DISCORD_TOKEN, "TELEGRAM_BOT_TOKEN": TG_TOKEN, "API_TOKEN": API_TOKEN.strip()}.items() if not v]
    if not os.getenv("ROUTES") and not TG_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID o ROUTES")
    if missing:
        raise SystemExit(f"Faltan variables en .env: {', '.join(missing)}")
    Bridge(Telegram(TG_TOKEN, TG_CHAT_ID), Webhook(WEBHOOK_URLS, WEBHOOK_SECRET)).run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
