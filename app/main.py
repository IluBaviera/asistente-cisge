from fastapi import FastAPI, Request
from pydantic import BaseModel
from app.motor import consultar
from app.motor import log_consultas
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
    try:
        value = data["entry"][0]["changes"][0]["value"]
        if "messages" not in value:
            return {"status": "ok"}
        msg = value["messages"][0]
        msg_id  = msg["id"]
        mensaje = msg["text"]["body"]
        numero  = msg["from"]

        # Whitelist fase de pruebas
        if numero not in NUMEROS_PERMITIDOS:
            logger.info(f"Número no autorizado ignorado: {numero}")
            return {"status": "ok"}

        # Deduplicación
        if msg_id in mensajes_procesados:
            logger.info(f"Mensaje duplicado ignorado: {msg_id}")
            return {"status": "duplicado"}

        mensajes_procesados.add(msg_id)
        if len(mensajes_procesados) > MAX_IDS:
            mensajes_procesados.clear()

        _, respuesta = consultar(mensaje)
        await enviar_whatsapp(numero, respuesta)

    except Exception as e:
        logger.error(f"Error en webhook: {e}", exc_info=True)

    return {"status": "ok"}

async def enviar_whatsapp(numero: str, texto: str):
    url     = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    body    = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": texto}
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=body, headers=headers)
        logger.info(f"WhatsApp API response: {r.status_code} {r.text}")
