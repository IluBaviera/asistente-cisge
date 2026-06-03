import os
import re
import json
import logging
from openai import AsyncOpenAI
from app.db import cargar_historial, guardar_mensajes
from app.tools import TOOLS_SCHEMA, tool_buscar_producto, tool_ver_stock, tool_generar_cotizacion
from app.motor import (
    consultar,
    buscar_por_tipo_medida_marca,
    formatear_resultado,
    formatear_multi_marca,
    formatear_lista,
    df as motor_df,
)

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_MODEL  = "gpt-4.1-mini"

_MOTOR_VACIO = ("No encontré ese producto", "¡Hola! 👋")

# ── Prompt 1: parser interno (sin tools, devuelve JSON) ──────────────────────
_PARSER_PROMPT = """\
Eres un parser de consultas comerciales para CISGE Perú.
Extrae del texto estos campos y devuelve SOLO JSON válido sin texto adicional:
{
  "subfamilias": [],
  "tipo": "",
  "medida": "",
  "marca": "",
  "color": "",
  "presion": "",
  "es_saludo": false
}
subfamilias: lista de subfamilias ERP posibles: "MANGUERAS HIDRAULICAS", "ESPIGAS I", "ESPIGAS II", "FERRULAS", "ADAPTADORES I", "ADAPTADORES II", "VALVULAS", etc.
tipo: tipo de producto: R1, R2, 4SH, NPT, JIC, BSP, MACHO, HEMBRA, etc.
medida: fracción o decimal sin texto: 1/2, 3/4, 1, 1 1/4
marca: marca oficial: QF, JDEFLEX, VITILLO, MACTUBI, AF, LT, DME, etc.
color: A=Amarillo, N=Negro, R=Rojo — solo si se menciona explícitamente
presion: si se menciona presión de trabajo
es_saludo: true si el mensaje es un saludo o consulta no relacionada con productos
Aliases de marcas: JDE=JDEFLEX, VITI=VITILLO, MACTU=MACTUBI
Si es_saludo es true, deja todos los demás campos vacíos."""

# ── Prompt 2: asistente conversacional (responde al usuario) ─────────────────
_AGENT_PROMPT = """\
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
    """Flujo: E1/E2 motor → parser GPT → E3 directo → E4 GPT conversacional."""
    historial = cargar_historial(numero_wa)

    logger.info(f"agente [{numero_wa}]: historial={len(historial)} msgs | "
                + " | ".join(f"{m['role']}:{m['content'][:40]!r}" for m in historial)
                if historial else f"agente [{numero_wa}]: historial vacío")

    # ── E1/E2: motor regex ────────────────────────────────────────────────────
    try:
        _, respuesta_motor = consultar(mensaje)
    except Exception as e:
        logger.warning(f"motor.consultar error: {e}")
        respuesta_motor = ""

    logger.info(f"agente [{numero_wa}]: motor → {respuesta_motor[:80]!r}")
    if respuesta_motor and not respuesta_motor.startswith(_MOTOR_VACIO):
        # Si el motor encontró >15 productos, es demasiado amplio → refinar con GPT
        m = re.search(r'Encontré \*(\d+) productos\*', respuesta_motor)
        if m and int(m.group(1)) > 15:
            logger.info(f"agente [{numero_wa}]: motor retornó {m.group(1)} productos → refinar con GPT")
        else:
            logger.info(f"agente [{numero_wa}]: motor encontró resultado (sin GPT)")
            guardar_mensajes(numero_wa, mensaje, respuesta_motor)
            return respuesta_motor

    # ── GPT parser (recibe historial para entender referencias vagas) ────────
    parsed = await _parsear(mensaje, historial)
    logger.info(f"agente [{numero_wa}]: parser → {parsed}")

    # ── Saludo / consulta no relacionada ─────────────────────────────────────
    if parsed.get("es_saludo"):
        respuesta = await _gpt_conversacional(mensaje, historial)
        guardar_mensajes(numero_wa, mensaje, respuesta)
        return respuesta

    # ── E3: búsqueda directa con campos del parser ────────────────────────────
    respuesta_e3 = _buscar_con_parsed(parsed)
    if respuesta_e3:
        logger.info(f"agente [{numero_wa}]: E3 encontró resultado")
        guardar_mensajes(numero_wa, mensaje, respuesta_e3)
        return respuesta_e3

    # ── E4: GPT conversacional como fallback ──────────────────────────────────
    logger.info(f"agente [{numero_wa}]: E4 fallback a GPT conversacional")
    respuesta = await _gpt_conversacional(mensaje, historial)
    guardar_mensajes(numero_wa, mensaje, respuesta)
    return respuesta


def _grupos_disponibles() -> str:
    """Lista de grupos únicos del DataFrame, ordenados, para inyectar en el parser."""
    grupos = sorted(motor_df["grupo"].dropna().unique().tolist())
    return ", ".join(f'"{g}"' for g in grupos)


async def _parsear(mensaje: str, historial: list) -> dict:
    """Llama a GPT sin tools para extraer campos estructurados.
    Inyecta la lista real de grupos del ERP para que GPT elija el string exacto."""
    try:
        prompt = _PARSER_PROMPT + f"\n\nGrupos válidos en el catálogo (elige uno de estos exactamente para el campo 'tipo'):\n{_grupos_disponibles()}"
        messages = [{"role": "system", "content": prompt}]
        messages.extend(historial[-4:])   # últimos 2 turnos de contexto
        messages.append({"role": "user", "content": mensaje})
        completion = await _client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            temperature=0,
        )
        return json.loads(completion.choices[0].message.content.strip())
    except Exception as e:
        logger.warning(f"_parsear error: {e}")
        return {"es_saludo": False}


def _buscar_con_parsed(parsed: dict) -> str:
    """E3: llama a buscar_por_tipo_medida_marca() con campos del parser."""
    tipo       = parsed.get("tipo") or None
    medida     = parsed.get("medida") or None
    marca      = parsed.get("marca") or None
    presion    = parsed.get("presion") or None
    color      = parsed.get("color") or None
    subfamilias = parsed.get("subfamilias") or None

    if not any([tipo, medida, marca, subfamilias]):
        logger.info("E3: sin campos suficientes para buscar")
        return ""

    subtipo_ht = color if tipo == "HT" else None
    logger.info(
        f"E3: buscar_por_tipo_medida_marca("
        f"tipo={tipo!r}, medida={medida!r}, marca={marca!r}, "
        f"presion={presion!r}, subfamilias={subfamilias})"
    )
    resultados = buscar_por_tipo_medida_marca(
        tipo=tipo, medida=medida, marca=marca, presion=presion,
        subtipo=subtipo_ht, subfamilias=subfamilias,
    )
    logger.info(f"E3: DataFrame → {len(resultados)} filas")

    # Retry sin tipo si subfamilias presentes pero no hubo match de grupo/tipo_cod
    if resultados.empty and subfamilias and tipo:
        logger.info("E3: retry sin tipo (subfamilias + medida + marca)")
        resultados = buscar_por_tipo_medida_marca(
            medida=medida, marca=marca, presion=presion, subfamilias=subfamilias,
        )
        logger.info(f"E3 retry: DataFrame → {len(resultados)} filas")

    if resultados.empty:
        return ""

    if len(resultados) == 1:
        return formatear_resultado(resultados.iloc[0])

    if resultados["codigo"].nunique() == 1:
        return formatear_multi_marca(resultados)

    if len(resultados) <= 12:
        return formatear_lista(resultados, f"Encontré {len(resultados)} opciones:")

    # >12: pedir refinamiento
    marcas = resultados["marca"].unique()
    meds   = resultados["medida_cod"].dropna().unique()[:8]
    detalle = []
    if not marca:
        detalle.append(f"Marca: {', '.join(marcas)}")
    if not medida:
        detalle.append(f"Medida: {', '.join(meds)}")
    return (
        f"Encontré {len(resultados)} productos.\n\n"
        "¿Puedes especificar?\n" + "\n".join(detalle)
    )


async def _gpt_conversacional(mensaje: str, historial: list) -> str:
    """GPT con tools para saludos y fallback E4."""
    messages = [{"role": "system", "content": _AGENT_PROMPT}]
    messages.extend(historial)
    messages.append({"role": "user", "content": mensaje})
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

    completion = await _client.chat.completions.create(
        model=_MODEL,
        messages=messages,
    )
    return completion.choices[0].message.content or ""
