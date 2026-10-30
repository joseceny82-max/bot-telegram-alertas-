# Discord → Telegram alerts + API

Lee los canales de carrito y compra-completada (ATM y RM) de Discord y:
1. Reenvía cada alerta al grupo de Telegram que le toca (`ROUTES`).
2. La expone en una **API HTTP** para el panel de la app (`/api/alerts`, `/api/alerts/stream`).
3. Opcional: la empuja por **webhook** a otra URL (`WEBHOOK_URLS`).

## Variables de entorno
| Variable | Descripción |
|---|---|
| `DISCORD_TOKEN` | Token del bot (Developer Portal → Bot → Reset Token). Message Content Intent activado. |
| `TELEGRAM_BOT_TOKEN` | Token de @BotFather |
| `ROUTES` | `canal_discord:chat_telegram,...` (un canal puede ir a varios chats repitiéndolo) |
| `API_TOKEN` | Token que la app debe enviar (`Authorization: Bearer …` o `?token=`). **Obligatorio en Railway.** |
| `CORS_ORIGIN` | Origen permitido para el panel (por defecto `*`) |
| `BACKFILL` | Mensajes por canal que se cargan del historial al arrancar (50) |
| `WEBHOOK_URLS` / `WEBHOOK_SECRET` | Opcional: POST JSON firmado (`X-Signature-256: sha256=HMAC`) |
| `PORT` | Lo pone Railway; en local 8080 |

## API
- `GET /health` → `{"ok": true, "alerts": N}` (sin token)
- `GET /api/alerts?type=carrito|compra_completada&section=ATM|RM&since=<ISO>&limit=50`
- `GET /api/alerts/stream` → Server-Sent Events (`event: alert`) en tiempo real

Ejemplo de alerta (`alerts[i]`):
```json
{"event":"compra_completada","section":"ATM","timestamp":"2026-10-30T08:20:21+00:00",
 "message_url":"https://discord.com/channels/…","title":"✅ Worker w4 — compra completada",
 "data":{"partido":"ATLÉTICO DE MADRID - FC BARCELONA LALIGA","worker":"w4","entradas":2,
         "total":"194.50 €","total_eur":194.5,"sectores":"S_417","evento_url":"https://…","url":"https://…",
         "asientos":[{"sector":"S_421","fila":"6","asiento":"30","precio_eur":97.25}]},
 "fields":{…}, "image":"https://cdn.discordapp.com/…"}
```
Panel en el navegador:
```js
const es = new EventSource("https://TU-APP.up.railway.app/api/alerts/stream?token=API_TOKEN");
es.addEventListener("alert", e => pintar(JSON.parse(e.data)));
```

## Railway (24/7)
1. Sube esta carpeta a un repo de GitHub (el `.gitignore` ya excluye `.env`).
2. Railway → New Project → Deploy from GitHub repo.
3. Variables: copia las del `.env` (`DISCORD_TOKEN`, `TELEGRAM_BOT_TOKEN`, `ROUTES`) y añade `API_TOKEN`.
4. Settings → Networking → **Generate Domain** → esa es la URL para la app.
5. **Apaga el `start.bat` local**: si hay dos instancias, Telegram recibe cada alerta dos veces.

## Local (Windows)
`start.bat` (arranca bot + API en http://localhost:8080). Tests: `pip install pytest && pytest -q`
