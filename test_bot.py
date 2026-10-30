import asyncio
import json

import aiohttp

from aiohttp import web

import bot


def test_format_escapes_and_embeds():
    txt = bot.format_message("Monitor", "compras", "Precio <bajo> & stock",
                             [{"title": "Zapas X", "url": "https://shop/x", "description": "Talla 42",
                               "fields": [{"name": "Precio", "value": "99€"}]}],
                             "https://discord.com/channels/1/2/3")
    assert "Precio &lt;bajo&gt; &amp; stock" in txt
    assert '<b><a href="https://shop/x">Zapas X</a></b>' in txt
    assert "<b>Precio:</b> 99€" in txt
    assert "Ver en Discord" in txt


def test_first_image_priority_and_truncate():
    assert bot.first_image([{"url": "a.png", "content_type": "image/png"}], [{"image": {"url": "e.png"}}]) == "a.png"
    assert bot.first_image([], [{"thumbnail": {"url": "t.png"}}]) == "t.png"
    assert bot.first_image([{"url": "f.pdf", "content_type": "application/pdf"}], []) is None
    assert len(bot.truncate("x" * 5000, 4096)) == 4096


def test_telegram_client_against_local_server():
    """Servidor HTTP local que imita la Bot API: comprueba payload, 429 con reintento y fallback de foto."""
    calls = []

    async def handler(request):
        method = request.match_info["method"]
        body = await request.json()
        calls.append((method, body))
        if method == "sendPhoto":
            return web.json_response({"ok": False, "description": "bad photo"}, status=400)
        if len([c for c in calls if c[0] == "sendMessage"]) == 1:
            return web.json_response({"ok": False, "parameters": {"retry_after": 0.01}}, status=429)
        return web.json_response({"ok": True, "result": {}})

    async def run():
        app = web.Application()
        app.router.add_post("/botTOKEN/{method}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 8765)
        await site.start()
        tg = bot.Telegram("TOKEN", "-100123")
        tg.base = "http://127.0.0.1:8765/botTOKEN"
        ok = await tg.send("<b>hola</b>", "https://img/x.png")
        await tg.close()
        await runner.cleanup()
        return ok

    assert asyncio.run(run()) is True
    assert [c[0] for c in calls] == ["sendPhoto", "sendMessage", "sendMessage"]
    assert calls[1][1]["chat_id"] == "-100123" and calls[1][1]["parse_mode"] == "HTML"


def test_bridge_on_message_filters_and_forwards():
    from types import SimpleNamespace as NS
    sent = []

    class FakeTG:
        async def send(self, text, image, chat=None):
            sent.append((text, image)); return True

    async def run():
        b = bot.Bridge(FakeTG())
        b._connection.user = NS(id=1)
        msg = lambda cid: NS(id=9, channel=NS(id=cid, name="compras"), author=NS(id=2, display_name="Monitor"),
                             content="Oferta", embeds=[], attachments=[], jump_url="https://discord.com/x",
                             created_at=__import__("datetime").datetime(2026, 10, 30))
        bot.ROUTES = {1496923066205470911: ["-1"]}
        await b.on_message(msg(123))                      # otro canal -> ignorado
        await b.on_message(msg(1496923066205470911))       # canal vigilado -> reenviado
    asyncio.run(run())
    assert len(sent) == 1 and "Oferta" in sent[0][0]


def test_get_chat_id_against_local_server(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import json

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = {"ok": True, "result": [{"channel_post": {"chat": {"id": -1001234, "title": "Alertas"}}},
                                           {"message": {"chat": {"id": 55, "first_name": "Juanjo"}}}]}
            data = json.dumps(body).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(data)
        def log_message(self, *a): pass

    srv = HTTPServer(("127.0.0.1", 8766), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    import get_chat_id
    monkeypatch.setattr(get_chat_id, "API", "http://127.0.0.1:8766")
    assert get_chat_id.find_chats("T") == {-1001234: "Alertas", 55: "Juanjo"}
    srv.server_close()


def test_compra_completada_format():
    embed = {"author": {"name": "✅ Compra completada · ATM - FCB"}, "title": "✅  Worker w4 — compra completada",
             "description": "**2 entradas** compradas por **194.50€**. Pago confirmado.",
             "fields": [{"name": "💰 Total", "value": "**194.50 €**"},
                        {"name": "🔗 URL", "value": "[https://entradas.x/check…](https://entradas.x/checkout/success?a=1&b=2)"}],
             "footer": {"text": "RB Bot · tipo: worker_done · worker w4"}}
    txt = bot.format_message("RB Bot", "ATM · compra-completada", "✅ **Compra completada** · ATM - FCB", [embed], "https://d/x")
    assert txt.startswith("✅ <b>ATM · compra-completada</b>")
    assert "**" not in txt and "<b>194.50 €</b>" in txt and "<b>2 entradas</b>" in txt
    assert '<a href="https://entradas.x/checkout/success?a=1&amp;b=2">https://entradas.x/check…</a>' in txt
    assert "<i>RB Bot · tipo: worker_done · worker w4</i>" in txt
    assert bot.md("a <b> & `c`") == "a &lt;b&gt; &amp; <code>c</code>"


def test_routes():
    r = bot.parse_routes("1:-100A, 2:-100A,3:-100B,3:-100C", "X", {9})
    assert r == {1: ["-100A"], 2: ["-100A"], 3: ["-100B", "-100C"]}
    assert bot.parse_routes("", "X", {9}) == {9: ["X"]}


REAL_EMBED = {"author": {"name": "✅ Compra completada · ATLÉTICO DE MADRID - FC BARCELONA LALIGA"},
              "title": "✅  Worker w4 — compra completada",
              "description": "**2 entradas** compradas por **194.50€**. Pago confirmado.",
              "fields": [{"name": "⚽ Partido", "value": "ATLÉTICO DE MADRID - FC BARCELONA LALIGA"},
                         {"name": "🧩 Worker", "value": "w4"}, {"name": "🎫 Entradas", "value": "2"},
                         {"name": "💰 Total", "value": "**194.50 €**"}, {"name": "📍 Sectores", "value": "S_417"},
                         {"name": "🎟 Página del evento", "value": "[https://entradas.x/sel…](https://entradas.x/select/2976109)"},
                         {"name": "🔗 URL", "value": "[https://entradas.x/chk…](https://entradas.x/checkout/success)"}],
              "footer": {"text": "RB Bot · tipo: worker_done · worker w4"}}


def test_build_event_compra():
    ev = bot.build_event("ATM", "compra-completada", 1496936889544998972, 99, "https://d/x", "2026-10-30T08:20:00+00:00",
                         "RB Bot", "✅ **Compra completada** · ATM - FCB · 2 entradas · 194.50 €", [REAL_EMBED], None)
    assert ev["event"] == "compra_completada" and ev["section"] == "ATM"
    assert ev["data"] == {"partido": "ATLÉTICO DE MADRID - FC BARCELONA LALIGA", "worker": "w4", "entradas": 2,
                          "total": "194.50 €", "total_eur": 194.5, "sectores": "S_417",
                          "evento_url": "https://entradas.x/select/2976109", "url": "https://entradas.x/checkout/success"}
    assert ev["content"] == "✅ Compra completada · ATM - FCB · 2 entradas · 194.50 €"
    assert ev["description"] == "2 entradas compradas por 194.50€. Pago confirmado."
    assert bot.build_event("RM", "carrito", 1, 2, "u", "t", "a", "", [], None)["event"] == "carrito"


def test_webhook_post_signed_and_retry():
    import hashlib, hmac, json as js
    got = []

    async def handler(request):
        body = await request.read()
        got.append((dict(request.headers), body))
        if len(got) == 1:
            return web.Response(status=503)
        return web.json_response({"ok": True})

    async def run():
        app = web.Application(); app.router.add_post("/hook", handler)
        runner = web.AppRunner(app); await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 8767).start()
        wh = bot.Webhook(["http://127.0.0.1:8767/hook"], "s3cr3t")
        res = await wh.send({"event": "carrito", "x": "ñ"})
        await wh.close(); await runner.cleanup()
        return res

    assert asyncio.run(run()) == [True]
    assert len(got) == 2
    headers, body = got[-1]
    assert js.loads(body) == {"event": "carrito", "x": "ñ"}
    assert headers["X-Event-Type"] == "carrito"
    assert headers["X-Signature-256"] == "sha256=" + hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()


def _ev(mid, event="carrito", section="ATM", ts="2026-10-30T10:00:00"):
    return {"event": event, "section": section, "message_id": str(mid), "timestamp": ts}


def test_store_dedupe_filters():
    st = bot.Store(size=3)
    assert st.add(_ev(1)) and not st.add(_ev(1))
    st.add(_ev(2, "compra_completada", "RM", "2026-10-30T11:00:00")); st.add(_ev(3, ts="2026-10-30T12:00:00"))
    st.add(_ev(4, ts="2026-10-30T13:00:00"))          # expulsa el 1
    assert [e["message_id"] for e in st.query()] == ["4", "3", "2"]
    assert [e["message_id"] for e in st.query(event="compra_completada")] == ["2"]
    assert [e["message_id"] for e in st.query(section="atm", since="2026-10-30T12:30:00")] == ["4"]
    assert st.add(_ev(1))                               # ya no está en ids


def test_api_auth_filters_and_stream():
    st = bot.Store()
    st.add(_ev(1)); st.add(_ev(2, "compra_completada", "RM", "2026-10-30T11:00:00"))

    async def run():
        runner = web.AppRunner(bot.make_api(st, "tok", "*", ping=0.2)); await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 8769).start()
        base = "http://127.0.0.1:8769"
        async with aiohttp.ClientSession() as s:
            r = {}
            async with s.get(base + "/health") as x: r["health"] = (x.status, await x.json())
            async with s.get(base + "/api/alerts") as x: r["noauth"] = x.status
            async with s.get(base + "/api/alerts", headers={"Authorization": "Bearer mal"}) as x: r["bad"] = x.status
            async with s.get(base + "/api/alerts?type=compra_completada", headers={"Authorization": "Bearer tok"}) as x:
                r["filtered"] = (x.status, await x.json(), x.headers.get("Access-Control-Allow-Origin"))
            async with s.get(base + "/api/alerts?token=tok&type=x") as x: r["badtype"] = x.status
            async with s.get(base + "/api/alerts/stream?token=tok") as x:
                await asyncio.sleep(0.1); st.add(_ev(9, ts="2026-10-30T14:00:00"))
                line = b""
                while b"data:" not in line:
                    line = await x.content.readline()
                r["sse"] = json.loads(line.decode()[5:])
        await runner.cleanup()
        return r

    r = asyncio.run(run())
    assert r["health"] == (200, {"ok": True, "alerts": 2})
    assert r["noauth"] == 401 and r["bad"] == 401 and r["badtype"] == 400
    st_, body, cors = r["filtered"]
    assert st_ == 200 and body["count"] == 1 and body["alerts"][0]["message_id"] == "2" and cors == "*"
    assert r["sse"]["message_id"] == "9"


def test_build_event_rm_carrito_seats():
    embed = {"title": "🛒  REAL MADRID CF - RB LEIPZIG", "description": "Esperando tu aprobación en el panel.",
             "fields": [{"name": "📍 Sector 421 · 2o Anf Fondo Norte",
                         "value": "🪑 Fila **4** · Asiento **8** — 193,45 €\n🪑 Fila **4** · Asiento **9** — 193,45 €"},
                        {"name": "💰 Total", "value": "**386,90 €** · 2 entradas"}, {"name": "🧩 Worker", "value": "w21"}]}
    ev = bot.build_event("RM", "carrito", 1, 2, "u", "t", "a",
                         "🛒 **Carrito listo** · REAL MADRID CF - RB LEIPZIG · 2 entradas · 386,90 €", [embed], None)
    d = ev["data"]
    assert d["partido"] == "REAL MADRID CF - RB LEIPZIG" and d["entradas"] == 2 and d["total_eur"] == 386.9
    assert d["worker"] == "w21" and d["sectores"] == "421 · 2o Anf Fondo Norte"
    assert d["asientos"] == [{"sector": "421 · 2o Anf Fondo Norte", "fila": "4", "asiento": "8", "precio_eur": 193.45},
                             {"sector": "421 · 2o Anf Fondo Norte", "fila": "4", "asiento": "9", "precio_eur": 193.45}]
    assert bot.plain("a &amp; b") == "a & b"
