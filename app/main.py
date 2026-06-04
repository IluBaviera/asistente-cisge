from fastapi import FastAPI, Request
from pydantic import BaseModel
from app.motor import consultar
from app.motor import log_consultas
from app.motor import refresh_stock_loop
from app.agente import agente_cisge, procesar_imagen_whatsapp
import asyncio
import httpx
import os
import logging

logger = logging.getLogger(__name__)

app = FastAPI()

RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://asistente-cisge.onrender.com")

async def _keep_alive():
    await asyncio.sleep(60)  # esperar a que el servidor esté completamente listo
    while True:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{RENDER_URL}/ping", timeout=10)
                logger.info(f"Keep-alive ping: {r.status_code}")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")
        await asyncio.sleep(600)  # 10 minutos

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(_keep_alive())
    asyncio.create_task(refresh_stock_loop())

# ── tokens de Meta ──────────────────────────────
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
VERIFY_TOKEN   = os.getenv("VERIFY_TOKEN")
PHONE_ID       = os.getenv("PHONE_NUMBER_ID")

# ── whitelist fase de pruebas ────────────────────
NUMEROS_PERMITIDOS = {
    "51943584251",   # Pablo (pruebas)
    "51981234344",   # Eduardo (vendedor)
    "51958678366",   # Guillermo (vendedor)
    "51982207673",   # Carlos Toledo (vendedor)
}

# ── deduplicación de mensajes ────────────────────
mensajes_procesados: set = set()
MAX_IDS = 1000

# ── endpoints existentes ─────────────────────────
@app.get("/")
def root():
    return {"status": "ok"}

@app.api_route("/ping", methods=["GET", "HEAD"])
def ping():
    return {"status": "alive"}

@app.get("/logs")
def ver_logs():
    return log_consultas[-20:]

class Query(BaseModel):
    mensaje: str

@app.post("/consultar")
def consultar_api(query: Query):
    _, respuesta = consultar(query.mensaje)
    return {"respuesta": respuesta}

# ── webhook Meta ─────────────────────────────────
@app.get("/webhook")
def verificar_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(params["hub.challenge"])
    return {"error": "token inválido"}

@app.post("/webhook")
async def recibir_mensaje(request: Request):
    data = await request.json()
    asyncio.create_task(_procesar_mensaje(data))
    return {"status": "ok"}

async def _procesar_mensaje(data: dict):
    try:
        value = data["entry"][0]["changes"][0]["value"]
        if "messages" not in value:
            return
        msg     = value["messages"][0]
        msg_id  = msg["id"]
        numero  = msg["from"]
        tipo    = msg.get("type", "text")

        # Whitelist fase de pruebas
        if numero not in NUMEROS_PERMITIDOS:
            logger.info(f"Número no autorizado ignorado: {numero}")
            return

        if msg_id in mensajes_procesados:
            return
        mensajes_procesados.add(msg_id)
        if len(mensajes_procesados) > MAX_IDS:
            mensajes_procesados.clear()

        await marcar_leido(msg_id)

        if tipo == "text":
            mensaje  = msg["text"]["body"]
            respuesta = await agente_cisge(mensaje, numero)
        elif tipo == "image":
            image_id  = msg["image"]["id"]
            respuesta = await procesar_imagen_whatsapp(image_id, numero)
        else:
            logger.info(f"Tipo de mensaje ignorado: {tipo}")
            respuesta = "Solo proceso mensajes de texto e imágenes de listas de productos. Para consultas escríbeme directamente."

        await enviar_whatsapp(numero, respuesta)
    except Exception as e:
        logger.error(f"Error en _procesar_mensaje: {e}", exc_info=True)

async def marcar_leido(msg_id: str):
    url     = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    body    = {"messaging_product": "whatsapp", "status": "read", "message_id": msg_id}
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=body, headers=headers, timeout=5)
    except Exception as e:
        logger.warning(f"marcar_leido falló: {e}")

def _dividir_mensaje(texto: str, limite: int = 4000) -> list[str]:
    """Divide texto en chunks <= limite, cortando en saltos de línea."""
    if len(texto) <= limite:
        return [texto]
    partes, bloque = [], ""
    for linea in texto.splitlines(keepends=True):
        if len(bloque) + len(linea) > limite:
            if bloque:
                partes.append(bloque.rstrip())
            bloque = linea
        else:
            bloque += linea
    if bloque.strip():
        partes.append(bloque.rstrip())
    return partes

async def enviar_whatsapp(numero: str, texto: str):
    url     = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        for parte in _dividir_mensaje(texto):
            body = {
                "messaging_product": "whatsapp",
                "to": numero,
                "type": "text",
                "text": {"body": parte}
            }
            r = await client.post(url, json=body, headers=headers)
            logger.info(f"WhatsApp API response: {r.status_code} {r.text}")
