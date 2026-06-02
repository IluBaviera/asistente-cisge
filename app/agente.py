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
Eres un parser de consultas comerciales para CISGE, distribuidora peruana.
Extrae del texto: tipo de manguera (R1/R2/4SH/4SP/AIR/etc), medida (fracción en pulgadas), marca (QF/JDEFLEX/VITILLO/MACTUBI/AF).
Evalúa tu confianza en la extracción: high/medium/low.
Devuelve SOLO JSON válido, sin texto adicional:
{"tipo":"","medida":"","marca":"","confidence":"high|medium|low","pregunta":"(solo si confidence es low, la pregunta específica a hacerle al usuario)"}
Si confidence es low, deja tipo/medida/marca vacíos y agrega el campo pregunta.
La medida siempre en formato numérico o fracción: 1/2, 3/4, 1, 1 1/4. Nunca escribas 'pulgada', 'media' ni texto adicional."""

_TOOL_MAP = {
    "tool_buscar_producto":   tool_buscar_producto,
    "tool_ver_stock":         tool_ver_stock,
    "tool_generar_cotizacion": tool_generar_cotizacion,
}


async def agente_cisge(mensaje: str, numero_wa: str) -> str:
    """Punto de entrada del agente conversacional. Retorna el texto de respuesta."""
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
    """Llama a GPT con soporte de tool calls. Resuelve hasta 5 rondas de tools."""
    for _ in range(5):
        completion = await _client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
        )

        msg = completion.choices[0].message

        # Sin tool call → respuesta final
        if not msg.tool_calls:
            return msg.content or ""

        # Agregar respuesta del asistente al hilo
        messages.append(msg)

        # Ejecutar cada tool call y agregar resultados
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

    # Seguridad: si se agotaron las rondas, pedir respuesta sin tools
    completion = await _client.chat.completions.create(
        model=_MODEL,
        messages=messages,
    )
    return completion.choices[0].message.content or ""
