import os
import json
import logging
from openai import AsyncOpenAI
from app.db import cargar_historial, guardar_mensajes
from app.tools import TOOLS_SCHEMA, tool_buscar_producto, tool_ver_stock, tool_generar_cotizacion

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_MODEL = "gpt-4.1-mini"

# ── Prompt 1: parser interno (nunca se envía al usuario) ─────────────────────
_PARSER_PROMPT = """\
Eres un parser de consultas comerciales para CISGE, distribuidora peruana.
Extrae del texto: tipo de manguera (R1/R2/4SH/4SP/AIR/etc), medida (fracción en pulgadas), marca (QF/JDEFLEX/VITILLO/MACTUBI/AF).
Evalúa tu confianza en la extracción: high/medium/low.
Devuelve SOLO JSON válido, sin texto adicional:
{"tipo":"","medida":"","marca":"","confidence":"high|medium|low","pregunta":"(solo si confidence es low, la pregunta específica a hacerle al usuario)"}
Si confidence es low, deja tipo/medida/marca vacíos y agrega el campo pregunta.
La medida siempre en formato numérico o fracción: 1/2, 3/4, 1, 1 1/4. Nunca escribas 'pulgada', 'media' ni texto adicional."""

# ── Prompt 2: asistente conversacional (responde al usuario) ─────────────────
_AGENT_PROMPT = """\
Eres el asistente comercial de CISGE, distribuidora peruana de mangueras hidráulicas y accesorios. Atiendes vendedores por WhatsApp.
PERSONALIDAD: Profesional, directo, respuestas cortas adaptadas a WhatsApp.
PRODUCTOS: Mangueras hidráulicas (R1,R2,4SH,4SP), aire, succión, espigas, ferrulas, adaptadores, válvulas. Marcas: QF, JDEFLEX, VITILLO, MACTUBI, AF. Precios en dólares + IGV.
REGLAS:
- Nunca inventes precios ni stock, solo usa las tools
- Respuestas en español, formato WhatsApp (sin markdown)
- Si tienes tipo/medida/marca del contexto, úsalos directamente en la tool sin preguntar de nuevo"""

_TOOL_MAP = {
    "tool_buscar_producto":    tool_buscar_producto,
    "tool_ver_stock":          tool_ver_stock,
    "tool_generar_cotizacion": tool_generar_cotizacion,
}


async def agente_cisge(mensaje: str, numero_wa: str) -> str:
    """Punto de entrada del agente. Retorna texto en lenguaje natural para el usuario."""
    historial = cargar_historial(numero_wa)

    try:
        respuesta_final = await _procesar(mensaje, historial)
    except Exception as e:
        logger.error(f"agente_cisge error para {numero_wa}: {e}", exc_info=True)
        respuesta_final = "Hubo un problema procesando tu consulta. Intenta de nuevo."

    guardar_mensajes(numero_wa, mensaje, respuesta_final)
    return respuesta_final


async def _parsear(mensaje: str) -> dict:
    """Paso 1 — parser interno. Devuelve dict con tipo/medida/marca/confidence."""
    completion = await _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _PARSER_PROMPT},
            {"role": "user",   "content": mensaje},
        ],
        temperature=0,
    )
    texto = completion.choices[0].message.content.strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        logger.warning(f"Parser devolvió JSON inválido: {texto!r}")
        return {"confidence": "low", "pregunta": "¿Qué producto necesitas?"}


async def _procesar(mensaje: str, historial: list) -> str:
    """Paso 2 — decide si responder directo o invocar tools."""
    parsed = await _parsear(mensaje)
    confidence = parsed.get("confidence", "low")

    # confidence=low → GPT responde en lenguaje natural sin tools
    if confidence == "low":
        pregunta = parsed.get("pregunta") or "¿Qué producto necesitas cotizar?"
        messages = [{"role": "system", "content": _AGENT_PROMPT}]
        messages.extend(historial)
        messages.append({"role": "user", "content": mensaje})
        messages.append({
            "role": "system",
            "content": f"El parser no pudo extraer datos suficientes. Responde al usuario con esta pregunta: {pregunta}",
        })
        completion = await _client.chat.completions.create(
            model=_MODEL,
            messages=messages,
        )
        return completion.choices[0].message.content or pregunta

    # confidence=high/medium → asistente con tools, contexto del parser como guía
    contexto_parser = (
        f"[Contexto extraído: tipo={parsed.get('tipo','')}, "
        f"medida={parsed.get('medida','')}, marca={parsed.get('marca','')}]"
    )
    messages = [{"role": "system", "content": _AGENT_PROMPT}]
    messages.extend(historial)
    messages.append({"role": "user", "content": f"{contexto_parser}\n{mensaje}"})

    return await _llamar_gpt(messages)


async def _llamar_gpt(messages: list) -> str:
    """Llama a GPT con tools. Resuelve hasta 5 rondas de tool calls."""
    for _ in range(5):
        completion = await _client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
        )
        msg = completion.choices[0].message

        if not msg.tool_calls:
            return msg.content or ""

        messages.append(msg)

        for tc in msg.tool_calls:
            nombre = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            fn = _TOOL_MAP.get(nombre)
            if fn:
                try:
                    resultado = fn(**args)
                except Exception as e:
                    resultado = f"Error al ejecutar {nombre}: {e}"
                    logger.warning(resultado)
            else:
                resultado = f"Tool desconocida: {nombre}"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": resultado,
            })

    # Agotadas las rondas → forzar respuesta sin tools
    completion = await _client.chat.completions.create(
        model=_MODEL,
        messages=messages,
    )
    return completion.choices[0].message.content or ""
