import os
import json
import logging
from openai import AsyncOpenAI
from app.db import cargar_historial, guardar_mensajes
from app.tools import TOOLS_SCHEMA, tool_buscar_producto, tool_ver_stock, tool_generar_cotizacion

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_MODEL = "gpt-4.1-mini"

_SYSTEM_PROMPT = """\
Eres el asistente comercial de CISGE, distribuidora peruana de mangueras hidráulicas y accesorios. Atiendes vendedores por WhatsApp.
PERSONALIDAD: Profesional, directo, respuestas cortas adaptadas a WhatsApp.
PRODUCTOS: Mangueras hidráulicas (R1,R2,4SH,4SP), aire, succión, espigas, ferrulas, adaptadores, válvulas. Marcas: QF, JDEFLEX, VITILLO, MACTUBI, AF. Precios en dólares + IGV.
REGLAS:
- Si el usuario saluda o hace una consulta no relacionada con productos, responde cordialmente y pregunta en qué puedes ayudarle. No pidas tipo/medida/marca ante un saludo.
- Nunca inventes precios ni stock, solo usa las tools.
- Respuestas en español, formato WhatsApp (sin markdown).
- Cuando tengas suficiente información para buscar un producto, llama la tool directamente sin preguntar de nuevo.
- Cuando el usuario use pronombres o referencias vagas como 'el r1', 'ese producto', 'en colonial', siempre revisa el historial de la conversación para identificar a qué producto se refiere antes de pedir aclaraciones.
- Cuando el usuario envíe múltiples productos en un solo mensaje separados por comas o saltos de línea con cantidades, interpreta cada línea como un ítem de cotización y llama a tool_generar_cotizacion con todos los ítems juntos sin pedir confirmación previa."""

_TOOL_MAP = {
    "tool_buscar_producto":    tool_buscar_producto,
    "tool_ver_stock":          tool_ver_stock,
    "tool_generar_cotizacion": tool_generar_cotizacion,
}


async def agente_cisge(mensaje: str, numero_wa: str) -> str:
    """Punto de entrada del agente. Una sola llamada a GPT con tools."""
    historial = cargar_historial(numero_wa)

    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(historial)
    messages.append({"role": "user", "content": mensaje})

    try:
        respuesta_final = await _llamar_gpt(messages)
    except Exception as e:
        logger.error(f"agente_cisge error para {numero_wa}: {e}", exc_info=True)
        respuesta_final = "Hubo un problema procesando tu consulta. Intenta de nuevo."

    guardar_mensajes(numero_wa, mensaje, respuesta_final)
    return respuesta_final


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
