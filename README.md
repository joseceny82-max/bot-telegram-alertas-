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
| `API_TOKEN` | Token que la app debe enviar (`Authorization: Bearer …`). **Obligatorio en todos los entornos.** |
| `CORS_ORIGIN` | Origen permitido para el panel (vacío por defecto; configura la URL exacta del panel) |
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
 "data":{"partido":"EQUIPO A - EQUIPO B","worker":"w4","entradas":2,
         "total":"123.45 €","total_eur":123.45,"sectores":"S_100","evento_url":"https://…","url":"https://…",
         "asientos":[{"sector":"S_421","fila":"6","asiento":"30","precio_eur":97.25}]},
 "fields":{…}, "image":"https://cdn.discordapp.com/…"}
```
Para consultar la API, envía `Authorization: Bearer <API_TOKEN>` por HTTPS.
El token no se acepta en la URL. Para el flujo SSE utiliza un cliente que admita
cabeceras, por ejemplo `fetch` con lectura de `response.body`; `EventSource`
nativo no permite añadir la cabecera y necesita adaptarse. No incluyas un token
de servicio compartido en código público del navegador: usa un intermediario
autenticado o un cliente de confianza.

## Railway (24/7)
1. Sube esta carpeta a un repo de GitHub (el `.gitignore` excluye `.env` y sus variantes).
2. Railway → New Project → Deploy from GitHub repo.
3. Variables: copia las del `.env` (`DISCORD_TOKEN`, `TELEGRAM_BOT_TOKEN`, `ROUTES`) y añade `API_TOKEN`.
4. Settings → Networking → **Generate Domain** → esa es la URL para la app.
5. **Apaga el `start.bat` local**: si hay dos instancias, Telegram recibe cada alerta dos veces.

## Local (Windows)
`start.bat` (arranca bot + API en http://localhost:8080). Tests: `pip install pytest && pytest -q`

## Seguridad

Configura un `API_TOKEN` largo y aleatorio como variable de entorno en Railway y en local. Sin él el bot no arranca. Limita `CORS_ORIGIN` al origen del panel y protege el acceso a ese panel. Mantén los tokens, identificadores y rutas reales fuera del repositorio. La limpieza de archivos actuales no elimina datos de commits anteriores.

## Pendiente para un futuro panel web

Actualmente solo se utiliza Telegram; no es necesario configurar `CORS_ORIGIN` para ese uso. Antes de incorporar un panel web, establece `CORS_ORIGIN` a su origen exacto, implementa acceso autenticado mediante un intermediario de confianza y evita exponer `API_TOKEN` en el navegador. El flujo de alertas requiere un cliente SSE que pueda enviar la cabecera `Authorization`; `EventSource` nativo no la admite. Comprueba la conexión y la autorización antes del despliegue.
