import os
import re
import json
import base64
import logging
import httpx
from openai import AsyncOpenAI
from app.db import cargar_historial, guardar_mensajes
from app.tools import TOOLS_SCHEMA, tool_buscar_producto, tool_ver_stock, tool_generar_cotizacion
from app.motor import (
    buscar_por_codigo,
    buscar_por_codigo_prefijo,
    buscar_por_tipo_medida_marca,
    formatear_resultado,
    formatear_multi_marca,
    formatear_lista,
    extraer_cantidad,
    extraer_descuento,
    df as motor_df,
)

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_MODEL  = "gpt-4.1-mini"

# Preguntas de intención sobre marcas → GPT directo (antes de cualquier búsqueda)
_INTENT_MARCAS = re.compile(
    r'\b(qu[eé]\s+marcas?|en\s+qu[eé]\s+marcas?|qu[eé]\s+marca\s+tiene|'
    r'qu[eé]\s+marca\s+tienen|en\s+cu[aá]les?\s+marcas?)\b', re.IGNORECASE
)

# ── Prompt 1: parser interno ──────────────────────────────────────────────────
_PARSER_PROMPT = """\
Eres un parser de consultas comerciales para CISGE Perú.
Extrae del texto estos campos y devuelve SOLO JSON válido sin texto adicional:
{
  "subfamilias": [],
  "tipo": "",
  "medida": "",
  "medidas": [],
  "marca": "",
  "color": "",
  "presion": "",
  "es_saludo": false
}
subfamilias: lista de subfamilias ERP posibles: "MANGUERAS HIDRAULICAS", "ESPIGAS I", "ESPIGAS II", "FERRULAS", "ADAPTADORES I", "ADAPTADORES II", "VALVULAS", etc.
tipo: tipo de producto exacto del catálogo. Si el usuario especificó subtipo (R1/R2/R12/etc.), inclúyelo (ej: "ESPIGA MACHO NPT R2"). Si no especificó, usa el prefijo base (ej: "ESPIGA MACHO NPT").
medida: primera medida mencionada como fracción: 1/2, 3/4, 1, 1 1/4
medidas: si el usuario menciona dos medidas separadas por "x" (ej: "3/8 x 3/8", "1/4 x 1/2"), extrae la lista ordenada: ["3/8", "3/8"]. Si hay una sola medida, dejar vacío [].
marca: marca oficial: QF, JDEFLEX, VITILLO, MACTUBI, AF, LT, DME, etc.
color: A=Amarillo, N=Negro, R=Rojo — solo si se menciona explícitamente
presion: si se menciona presión de trabajo
es_saludo: true si el mensaje es un saludo o consulta no relacionada con productos
Aliases de marcas: JDE=JDEFLEX, VITI=VITILLO, MACTU=MACTUBI
Si es_saludo es true, deja todos los demás campos vacíos.
Para el campo tipo: elige el grupo más general que aplique — si el usuario no especificó subtipo (R1/R2/R12/etc.), usa el prefijo base (ej: "ESPIGA MACHO NPT" en lugar de "ESPIGA MACHO NPT R2").
IMPORTANTE: Analiza SOLO el mensaje actual del usuario. Ignora las respuestas previas del asistente."""

# ── Prompt 2: asistente conversacional ───────────────────────────────────────
_AGENT_PROMPT = """\
Eres Lutong, el asistente comercial de CISGE, distribuidora peruana de mangueras hidráulicas y accesorios. Atiendes vendedores por WhatsApp.
PERSONALIDAD: Profesional, directo, respuestas cortas adaptadas a WhatsApp.
PRODUCTOS: Mangueras hidráulicas (R1,R2,4SH,4SP), aire, succión, espigas, ferrulas, adaptadores, válvulas. Marcas: QF, JDEFLEX, VITILLO, MACTUBI, AF. Precios en dólares + IGV.
INFORMACIÓN DE LA EMPRESA:
Razón social: Comercial CISGE S.A.C.
RUC: 20511843783
Sede principal: Jr. Edmundo Moreau 931, Lima (Lima Centro)
Sede San Luis: Calle Río Piura 120, San Luis
Teléfonos: (01) 451-0788 / (01) 452-5052
Web: www.comercialcisgesac.com.pe
Fundada: 2008
Rubro: Importación y distribución de mangueras hidráulicas, conexiones, adaptadores y accesorios industriales.
Horario de atención: Lunes a viernes de 8:00 a.m. a 5:30 p.m.

REGLAS:
- Tu nombre es Lutong. Si te preguntan quién eres o cómo te llamas, responde que eres Lutong, el asistente de CISGE.
- Si preguntan por información de la empresa no listada aquí, indica que no tienes ese dato y sugiere llamar al (01) 451-0788.
- Nunca inventes datos de la empresa.
- Si el usuario saluda o hace una consulta no relacionada con productos, responde cordialmente y pregunta en qué puedes ayudarle. No pidas tipo/medida/marca ante un saludo.
- Nunca inventes precios ni stock, solo usa las tools.
- Respuestas en español, formato WhatsApp (sin markdown).
- Cuando tengas suficiente información para buscar un producto, llama la tool directamente sin preguntar de nuevo.
- Cuando el usuario use pronombres o referencias vagas como 'el r1', 'ese producto', 'en colonial', siempre revisa el historial de la conversación para identificar a qué producto se refiere antes de pedir aclaraciones.
- Cuando el usuario envíe múltiples productos en un solo mensaje separados por comas o saltos de línea con cantidades, interpreta cada línea como un ítem de cotización y llama a tool_generar_cotizacion con todos los ítems juntos sin pedir confirmación previa.
- Cuando el usuario pregunte 'en qué marcas tienes X', 'qué marcas tienen X' o similar: busca el producto con tool_buscar_producto, extrae las marcas únicas de los resultados y lista SOLO las marcas disponibles con sus precios aproximados. No listes todos los productos."""

_TOOL_MAP = {
    "tool_buscar_producto":    tool_buscar_producto,
    "tool_ver_stock":          tool_ver_stock,
    "tool_generar_cotizacion": tool_generar_cotizacion,
}


async def agente_cisge(mensaje: str, numero_wa: str) -> str:
    """E1 código exacto → E2 prefijo → GPT parser → E3 campos → E4 GPT."""
    historial = cargar_historial(numero_wa)

    logger.info(f"agente [{numero_wa}]: historial={len(historial)} msgs | "
                + " | ".join(f"{m['role']}:{m['content'][:40]!r}" for m in historial)
                if historial else f"agente [{numero_wa}]: historial vacío")

    # ── Pre-check: intención de marcas → GPT directo ──────────────────────────
    if _INTENT_MARCAS.search(mensaje):
        logger.info(f"agente [{numero_wa}]: pregunta de marcas → GPT directo")
        respuesta = await _gpt_conversacional(mensaje, historial)
        guardar_mensajes(numero_wa, mensaje, respuesta)
        return respuesta

    # Limpiar cantidad y descuento para búsquedas de código
    cantidad  = extraer_cantidad(mensaje)
    descuento = extraer_descuento(mensaje)
    texto_cod = re.sub(r'\bx\s*\d+(?!\s*/\d)', '', mensaje).strip()
    texto_cod = re.sub(r'\b\d+\s*%', '', texto_cod).strip()

    # ── E1: código exacto ─────────────────────────────────────────────────────
    exactos = buscar_por_codigo(texto_cod)
    if not exactos.empty:
        logger.info(f"agente [{numero_wa}]: E1 código exacto ({exactos.iloc[0]['codigo']})")
        respuesta = (formatear_resultado(exactos.iloc[0], cantidad, descuento)
                     if len(exactos) == 1 else formatear_multi_marca(exactos))
        guardar_mensajes(numero_wa, mensaje, respuesta)
        return respuesta

    # ── E2: prefijo de código ─────────────────────────────────────────────────
    if len(texto_cod) >= 3:
        prefijo = buscar_por_codigo_prefijo(texto_cod)
        # Fallback VITILLO: letra de color extra (VT-TH1SNN08 → VT-TH1SN08)
        if prefijo.empty:
            m_vt = re.match(r'^(.+)([A-Z])(\d{2}(?:SL)?)$', texto_cod.upper().strip())
            if m_vt:
                alt = m_vt.group(1) + m_vt.group(3)
                alt_r = buscar_por_codigo_prefijo(alt)
                if not alt_r.empty:
                    prefijo = alt_r
                    logger.info(f"agente [{numero_wa}]: E2 VITILLO corregido → {alt}")

        if len(prefijo) == 1:
            fila = prefijo.iloc[0]
            logger.info(f"agente [{numero_wa}]: E2 prefijo único ({fila['codigo']})")
            respuesta = formatear_resultado(fila, cantidad, descuento)
            guardar_mensajes(numero_wa, mensaje, respuesta)
            return respuesta
        elif 1 < len(prefijo) <= 15:
            logger.info(f"agente [{numero_wa}]: E2 prefijo {len(prefijo)} resultados")
            respuesta = (formatear_multi_marca(prefijo) if prefijo["codigo"].nunique() == 1
                         else formatear_lista(prefijo, f"Encontré {len(prefijo)} productos con ese prefijo:"))
            guardar_mensajes(numero_wa, mensaje, respuesta)
            return respuesta
        elif len(prefijo) > 15:
            logger.info(f"agente [{numero_wa}]: E2 prefijo {len(prefijo)} resultados → lista truncada")
            lista = formatear_lista(prefijo.head(15), f"Mostrando 15 de {len(prefijo)} productos con ese prefijo:")
            respuesta = lista + "\n_Hay más resultados — escribe más caracteres para filtrar._"
            guardar_mensajes(numero_wa, mensaje, respuesta)
            return respuesta

    # ── GPT parser: lenguaje natural → campos estructurados ───────────────────
    parsed = await _parsear(mensaje, historial)
    logger.info(f"agente [{numero_wa}]: parser → {parsed}")

    if parsed.get("es_saludo"):
        respuesta = await _gpt_conversacional(mensaje, historial)
        guardar_mensajes(numero_wa, mensaje, respuesta)
        return respuesta

    # ── E3: buscar_por_tipo_medida_marca con campos del parser ────────────────
    respuesta_e3 = _buscar_con_parsed(parsed)
    if respuesta_e3:
        logger.info(f"agente [{numero_wa}]: E3 encontró resultado")
        guardar_mensajes(numero_wa, mensaje, respuesta_e3)
        return respuesta_e3

    # ── E4: GPT conversacional con tools ──────────────────────────────────────
    logger.info(f"agente [{numero_wa}]: E4 GPT conversacional")
    respuesta = await _gpt_conversacional(mensaje, historial)
    guardar_mensajes(numero_wa, mensaje, respuesta)
    return respuesta


def _grupos_disponibles() -> str:
    grupos = sorted(motor_df["grupo"].dropna().unique().tolist())
    return ", ".join(f'"{g}"' for g in grupos)


def _subfamilias_disponibles() -> str:
    subs = sorted(motor_df["subfamilia"].dropna().unique().tolist())
    return ", ".join(f'"{s}"' for s in subs)


_SUBFAMILIAS_VALIDAS: set = set()


def _validar_subfamilias(subfamilias: list) -> list | None:
    global _SUBFAMILIAS_VALIDAS
    if not _SUBFAMILIAS_VALIDAS:
        _SUBFAMILIAS_VALIDAS = set(motor_df["subfamilia"].dropna().unique())
    validas = [s for s in (subfamilias or []) if s in _SUBFAMILIAS_VALIDAS]
    return validas if validas else None


async def _parsear(mensaje: str, historial: list) -> dict:
    """Parser interno: lenguaje natural → JSON estructurado. Sin tools."""
    try:
        prompt = (
            _PARSER_PROMPT
            + f"\n\nSubfamilias válidas (usa SOLO estas en el campo 'subfamilias'):\n{_subfamilias_disponibles()}"
        )
        messages = [{"role": "system", "content": prompt},
                    {"role": "user", "content": mensaje}]
        completion = await _client.chat.completions.create(
            model=_MODEL, messages=messages, temperature=0,
        )
        return json.loads(completion.choices[0].message.content.strip())
    except Exception as e:
        logger.warning(f"_parsear error: {e}")
        return {"es_saludo": False}


def _buscar_con_parsed(parsed: dict) -> str:
    """E3: llama a buscar_por_tipo_medida_marca() con campos del parser."""
    tipo        = parsed.get("tipo") or None
    medida      = parsed.get("medida") or None
    medidas     = parsed.get("medidas") or []
    marca       = parsed.get("marca") or None
    presion     = parsed.get("presion") or None
    color       = parsed.get("color") or None
    subfamilias_raw = parsed.get("subfamilias") or []
    subfamilias = _validar_subfamilias(subfamilias_raw)
    if subfamilias_raw and subfamilias_raw != (subfamilias or []):
        logger.info(f"E3: subfamilias filtradas: {subfamilias_raw} → {subfamilias}")

    if not any([tipo, medida, marca, subfamilias]):
        logger.info("E3: sin campos suficientes para buscar")
        return ""

    subtipo_ht = color if tipo == "HT" else None
    logger.info(
        f"E3: buscar_por_tipo_medida_marca("
        f"tipo={tipo!r}, medida={medida!r}, medidas={medidas}, marca={marca!r}, "
        f"presion={presion!r}, subfamilias={subfamilias})"
    )
    resultados = buscar_por_tipo_medida_marca(
        tipo=tipo, medida=medida, marca=marca, presion=presion,
        subtipo=subtipo_ht, subfamilias=subfamilias, medidas=medidas or None,
    )
    logger.info(f"E3: DataFrame → {len(resultados)} filas")

    if resultados.empty:
        return ""

    if len(resultados) == 1:
        return formatear_resultado(resultados.iloc[0])

    if resultados["codigo"].nunique() == 1:
        return formatear_multi_marca(resultados)

    if len(resultados) <= 12:
        return formatear_lista(resultados, f"Encontré {len(resultados)} opciones:")

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
    """E4: GPT con tools para saludos y consultas que E3 no pudo resolver."""
    messages = [{"role": "system", "content": _AGENT_PROMPT}]
    messages.extend(historial)
    messages.append({"role": "user", "content": mensaje})
    return await _llamar_gpt(messages)


async def _llamar_gpt(messages: list) -> str:
    """Llama a GPT con tools. Resuelve hasta 5 rondas de tool calls."""
    for _ in range(5):
        completion = await _client.chat.completions.create(
            model=_MODEL, messages=messages, tools=TOOLS_SCHEMA, tool_choice="auto",
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
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": resultado})

    completion = await _client.chat.completions.create(model=_MODEL, messages=messages)
    return completion.choices[0].message.content or ""


# ── Procesamiento de imágenes WhatsApp ────────────────────────────────────────

_WA_TOKEN = os.getenv("WHATSAPP_TOKEN")

_OCR_PROMPT = """\
Eres un extractor de texto de imágenes para CISGE, distribuidora industrial peruana.
Tu único trabajo es extraer el texto de la imagen lo más fiel posible, sin interpretar ni reformatear.
Devuelve SOLO JSON: {"texto_extraido": "..."}
Si la imagen no contiene una lista de productos o texto legible, devuelve: {"texto_extraido": ""}"""


async def procesar_imagen_whatsapp(image_id: str, numero_wa: str) -> str:
    """Descarga imagen de WhatsApp, extrae texto con GPT-4o Vision y procesa cada línea."""
    headers_wa = {"Authorization": f"Bearer {_WA_TOKEN}"}

    # Paso 1 — obtener URL de la imagen desde Meta
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://graph.facebook.com/v19.0/{image_id}",
            headers=headers_wa, timeout=10,
        )
        r.raise_for_status()
        image_url = r.json().get("url")
        if not image_url:
            return "No pude obtener la imagen. Intenta de nuevo."

        # Paso 2 — descargar imagen en memoria
        r2 = await client.get(image_url, headers=headers_wa, timeout=20)
        r2.raise_for_status()
        image_b64 = base64.b64encode(r2.content).decode()
        mime = r2.headers.get("content-type", "image/jpeg").split(";")[0]

    # Paso 3 — OCR con GPT-4o Vision
    try:
        completion = await _client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _OCR_PROMPT},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{image_b64}"
                    }}
                ]},
            ],
            max_tokens=1000,
            temperature=0,
        )
        raw = completion.choices[0].message.content.strip()
        # Limpiar bloques markdown que GPT suele agregar alrededor del JSON
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        ocr = json.loads(raw)
        texto = ocr.get("texto_extraido", "").strip()
    except Exception as e:
        logger.warning(f"OCR error: {e}")
        return "Hubo un problema leyendo la imagen. Intenta de nuevo o escribe la lista directamente."

    # Paso 4 — imagen sin texto legible
    if not texto:
        return "No pude leer texto en la imagen. ¿Puedes enviar una foto más clara o escribir la lista directamente?"

    # Paso 5 — GPT interpreta el texto OCR y convierte a queries del motor
    lineas_ocr = [l.strip() for l in texto.splitlines() if l.strip()]
    logger.info(f"OCR [{numero_wa}]: {len(lineas_ocr)} líneas brutas extraídas")
    try:
        lineas = await _parsear_lista_ocr(texto)
        logger.info(f"OCR [{numero_wa}]: {len(lineas)} líneas interpretadas por GPT")
    except Exception as e:
        logger.warning(f"_parsear_lista_ocr error: {e} — usando líneas brutas")
        lineas = lineas_ocr

    # Paso 6 — cotizar todas las líneas en una sola llamada (formato compacto)
    from app.motor import cotizar_multiple
    try:
        respuesta_final = cotizar_multiple(lineas)
    except Exception as e:
        logger.warning(f"cotizar_multiple error: {e}")
        respuesta_final = "Pude leer la imagen pero hubo un error al cotizar. Escribe la lista directamente."

    # Paso 7 — guardar como un solo intercambio en historial
    guardar_mensajes(numero_wa, f"[imagen: {len(lineas)} ítems]", respuesta_final)
    return respuesta_final


_PARSEAR_LISTA_PROMPT = """\
Eres un intérprete de listas de productos para CISGE, distribuidora peruana de mangueras hidráulicas.
Recibirás texto extraído de una imagen con productos y cantidades.

Tu trabajo: convertir cada ítem en una línea que el motor de búsqueda entienda.
Formato de salida: SOLO un JSON array de strings, sin texto adicional.

Aliases comunes del sector hidráulico (normaliza siempre al término estándar):
- forx / forxs / orx = ORFS
- bssp / bsp p / bspp = BSPP
- bspt / bsp t = BSPT
- jic = JIC
- npt = NPT
- sae = SAE
- casco / casq = CASQUILLO
- gir / girat = GIRATORIO
- hex = HEXAGONAL
- red = REDUCTOR
- ext = EXTERIOR
- int = INTERIOR
- h = HEMBRA
- m = MACHO (solo si es conector, no medida)

Reglas de conversión:
- "1/4-r1 200"                   → "R1 1/4 x 200"
- "5/16-r1 100"                  → "R1 5/16 x 100"
- "espiga hembra forx 1\" 50"    → "espiga hembra ORFS 1\" x 50"
- "espiga hembra bssp 11/2\" 10" → "espiga hembra BSPP 1 1/2\" x 10"
- "casco r2 1\" 50"              → "casquillo R2 1\" x 50"
- "M4 200" (bajo encabezado "mang azul poliuretano") → "mang azul poliuretano M4 x 200"
- "11/2" o "11/4" sin espacio    → "1 1/2" y "1 1/4" (agregar espacio)
- Si la línea es solo un encabezado/separador sin cantidad, NO incluirla
- Si hay marca explícita (QF, JDE, LT, etc.), conservarla: "QF-R1-1/2 50" → "QF-R1-1/2 x 50"
- Conserva las cantidades con "x N" al final

Devuelve SOLO el JSON array: ["R1 1/4 x 200", "espiga hembra ORFS 1\" x 50", ...]"""


async def _parsear_lista_ocr(texto: str) -> list[str]:
    """GPT convierte texto OCR crudo en queries limpias para el motor."""
    completion = await _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _PARSEAR_LISTA_PROMPT},
            {"role": "user",   "content": texto},
        ],
        temperature=0,
    )
    raw = completion.choices[0].message.content.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    resultado = json.loads(raw)
    return [l for l in resultado if isinstance(l, str) and l.strip()]
