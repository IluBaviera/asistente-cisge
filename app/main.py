from fastapi import FastAPI, Request
from pydantic import BaseModel
from app.motor import consultar
from app.motor import log_consultas
import httpx
import os

app = FastAPI()

# ── tokens de Meta ──────────────────────────────
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")       # token que generaste
VERIFY_TOKEN   = os.getenv("VERIFY_TOKEN")         # tú lo inventas, ej: "cisge2024"
PHONE_ID       = os.getenv("PHONE_NUMBER_ID")      # el Phone Number ID de Meta

# ── endpoints existentes ─────────────────────────
@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/logs")
def ver_logs():
    return log_consultas[-20:]

class Query(BaseModel):
    mensaje: str

@app.post("/consultar")
def consultar_api(query: Query):
    return {"respuesta": consultar(query.mensaje)}

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
        mensaje = data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]
        numero  = data["entry"][0]["changes"][0]["value"]["messages"][0]["from"]
        respuesta = consultar(mensaje)
        await enviar_whatsapp(numero, respuesta)
    except Exception:
        pass
    return {"status": "ok"}

async def enviar_whatsapp(numero: str, texto: str):
    url = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    body = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": texto}
    }
    async with httpx.AsyncClient() as client:
        await client.post(url, json=body, headers=headers)
