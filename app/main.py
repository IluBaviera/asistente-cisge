from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.motor import consultar
from app.motor import log_consultas
from app.motor import refresh_stock_loop
from app.agente import agente_cisge, procesar_imagen_whatsapp
from app.db import cargar_vendedores
import asyncio
import hashlib
import hmac
import httpx
import json
import os
import pathlib
import logging

logger = logging.getLogger(__name__)

app = FastAPI()

RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://asistente-cisge.onrender.com")

# Referencias fuertes a tasks en vuelo: el event loop solo guarda referencias
# débiles, sin esto el GC puede cancelar un task a mitad de ejecución.
_tasks_activos: set = set()

def _crear_task(coro):
    task = asyncio.create_task(coro)
    _tasks_activos.add(task)
    task.add_done_callback(_tasks_activos.discard)
    return task

async def _keep_alive():
    await asyncio.sleep(60)  # esperar a que el servidor esté completamente listo
    while True:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{RENDER_URL}/ping", timeout=10)
                logger.info(f"Keep-alive ping: {r.status_code}")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")
        await _refrescar_vendedores()   # refrescar whitelist desde BD cada ciclo
        await asyncio.sleep(600)  # 10 minutos

@app.on_event("startup")
async def startup_event():
    await _refrescar_vendedores()       # carga inicial antes de atender mensajes
    _crear_task(_keep_alive())
    _crear_task(refresh_stock_loop())

# ── tokens de Meta ──────────────────────────────
WHATSAPP_TOKEN  = os.getenv("WHATSAPP_TOKEN")
VERIFY_TOKEN    = os.getenv("VERIFY_TOKEN")
PHONE_ID        = os.getenv("PHONE_NUMBER_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
if not META_APP_SECRET:
    logger.warning("META_APP_SECRET no configurada — webhook SIN validación de firma")


def _firma_valida(body: bytes, signature_header: str) -> bool:
    """Valida X-Hub-Signature-256 (HMAC-SHA256 del body con el App Secret de Meta)."""
    if not signature_header.startswith("sha256="):
        return False
    esperada = hmac.new(META_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header[7:], esperada)

# ── whitelist de vendedores ───────────────────────
# Fuente primaria: tabla Vendedor en BdAsistente (vía API /vendedores),
# refrescada periódicamente → alta/baja sin tocar código ni env var.
# Fallback: env var NUMEROS_PERMITIDOS, por si la BD no responde al arrancar.
_NUMEROS_ENV = {
    n.strip() for n in os.getenv("NUMEROS_PERMITIDOS", "").split(",") if n.strip()
}
VENDEDORES: dict = {}                          # numero_wa -> nombre (de la BD)
NUMEROS_PERMITIDOS: set = set(_NUMEROS_ENV)    # base inicial (fallback env var)
if not NUMEROS_PERMITIDOS:
    logger.warning("NUMEROS_PERMITIDOS (fallback) vacía — la whitelist dependerá de la tabla Vendedor")


async def _refrescar_vendedores():
    """Carga whitelist + nombres desde la tabla Vendedor (vía API). Si la BD no
    responde, conserva la whitelist actual (fallback env var) — nunca la vacía."""
    global VENDEDORES, NUMEROS_PERMITIDOS
    mapa = await asyncio.to_thread(cargar_vendedores)
    if mapa:
        VENDEDORES = mapa
        NUMEROS_PERMITIDOS = set(mapa.keys())
        logger.info(f"Whitelist desde BD: {len(mapa)} vendedores activos")
    else:
        logger.warning("Vendedores no disponibles en BD — se mantiene whitelist previa/env var")

# ── deduplicación de mensajes (LRU: expulsa los más antiguos, no todo de golpe) ──
mensajes_procesados: dict = {}   # dict preserva orden de inserción
MAX_IDS = 1000

def _ya_procesado(msg_id: str) -> bool:
    """True si el mensaje ya fue procesado; si no, lo registra (con expulsión LRU)."""
    if msg_id in mensajes_procesados:
        return True
    mensajes_procesados[msg_id] = None
    while len(mensajes_procesados) > MAX_IDS:
        mensajes_procesados.pop(next(iter(mensajes_procesados)))
    return False

# ── auth de endpoints internos ───────────────────
# Si INTERNAL_API_KEY no está configurada, los endpoints quedan abiertos
# (con warning) para no romper el deploy antes de crear la variable en Render.
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
if not INTERNAL_API_KEY:
    logger.warning("INTERNAL_API_KEY no configurada — /logs, /demandas y /consultar quedan SIN protección")

def _requiere_api_key(request: Request):
    if INTERNAL_API_KEY and request.headers.get("X-API-Key") != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="No autorizado")

# ── endpoints existentes ─────────────────────────
@app.get("/")
def root():
    return {"status": "ok"}

@app.api_route("/ping", methods=["GET", "HEAD"])
def ping():
    return {"status": "alive"}

@app.get("/logs")
def ver_logs(request: Request):
    _requiere_api_key(request)
    return list(log_consultas)[-20:]  # deque no soporta slicing

@app.get("/demandas")
def ver_demandas(request: Request):
    """Devuelve las demandas no encontradas en catálogo para análisis comercial."""
    _requiere_api_key(request)
    ruta = pathlib.Path(__file__).parent / "data" / "demandas_no_catalogo.jsonl"
    if not ruta.exists():
        return JSONResponse({"total": 0, "items": []})
    items = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                try:
                    items.append(json.loads(linea))
                except Exception:
                    pass
    return JSONResponse({"total": len(items), "items": items})

class Query(BaseModel):
    mensaje: str

@app.post("/consultar")
def consultar_api(query: Query, request: Request):
    _requiere_api_key(request)
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
    body = await request.body()
    if META_APP_SECRET:
        firma = request.headers.get("X-Hub-Signature-256", "")
        if not _firma_valida(body, firma):
            logger.warning("Webhook rechazado: firma X-Hub-Signature-256 inválida")
            raise HTTPException(status_code=403, detail="Firma inválida")
    data = json.loads(body)
    _crear_task(_procesar_mensaje(data))
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

        if _ya_procesado(msg_id):
            return

        nombre = VENDEDORES.get(numero, "")
        logger.info(f"Mensaje de {nombre or numero[-4:]} ({numero}) tipo={tipo}")

        await marcar_leido(msg_id)

        if tipo == "text":
            mensaje  = msg["text"]["body"]
            respuesta = await agente_cisge(mensaje, numero, nombre)
        elif tipo == "image":
            image_id  = msg["image"]["id"]
            respuesta = await procesar_imagen_whatsapp(image_id, numero)
        else:
            logger.info(f"Tipo de mensaje ignorado: {tipo}")
            respuesta = "Solo proceso mensajes de texto e imágenes de listas de productos. Para consultas escríbeme directamente."

        if respuesta:
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
