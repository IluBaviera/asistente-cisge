import os
import re
import logging
import pandas as pd
from datetime import datetime

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("cisge_consultas.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

log_consultas = []

# ─── RUTAS ────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
ruta_excel = os.path.join(BASE_DIR, "data", "mangueras_precios.xlsx")

# ─── TABLA NOMINAL ISO → PULGADAS ─────────────────────────────────────────────
# Fuente: estándar ISO 4397. QF-R2S-05 = 5/16 (error humano en BD corregido aquí)
MEDIDA_NOMINAL = {
    "02": "1/8",
    "03": "3/16",
    "04": "1/4",
    "05": "5/16",   # QF-R2S-05 desc dice 5/16 (no 5/8, error en BD)
    "06": "3/8",
    "08": "1/2",
    "10": "5/8",
    "12": "3/4",
    "14": "7/8",
    "16": "1",
    "20": "1 1/4",
    "24": "1 1/2",
    "32": "2",
    "40": "2 1/2",
    "48": "3",
    "56": "3 1/2",
    "64": "2 1/2", # SW-HCA-64: desc dice 2 1/2 (nominal 64 incorrecto en BD)
}

# ─── ALIAS DE MARCA ───────────────────────────────────────────────────────────
MARCA_ALIAS = {
    "qf":           "QF",
    "qingflex":     "QF",
    "af":           "AF",
    "jde":          "JDEFLEX",
    "jdeflex":      "JDEFLEX",
    "vt":           "VITILLO",
    "vitillo":      "VITILLO",
    "rsy":          "RUNNINGFLEX",
    "runningflex":  "RUNNINGFLEX",
    "running":      "RUNNINGFLEX",
    "sw":           "SWAGGER",
    "swagger":      "SWAGGER",
    "mactubi":      "MACTUBI",
    "hyp":          "HYP",
    "hypress":      "HYP",
}

# ─── ALIAS DE TIPO ────────────────────────────────────────────────────────────
TIPO_ALIAS = {
    # lenguaje natural → código de tipo en BD
    "aire":             "AIR",
    "air":              "AIR",
    "agua":             "AIR",        # mang agua/aire es AIR
    "gasolina":         "GL",
    "combustible":      "GL",
    "petroleo":         "GL",
    "petróleo":         "GL",
    "gl":               "GL",
    "vapor":            "STEAM",
    "steam":            "STEAM",
    "succion":          "SW",         # suction water
    "succión":          "SW",
    "succion agua":     "SW",
    "succion oil":      "SG",
    "succión oil":      "SG",
    "succion aceite":   "SG",
    "descarga agua":    "DW",
    "descarga aceite":  "DG",
    "descarga oil":     "DG",
    "multipropósito":   "MP",
    "multiproposito":   "MP",
    "multipropocito":   "MP",
    "multiprop":        "MP",
    "carwash":          "R2CW",
    "car wash":         "R2CW",
    "lavado auto":      "R2CW",
    "lavado":           "R2CW",
    "lisa":             "R1S",        # fallback — puede ser R1S o R2S
    "trenzada":         "R1",
    "trenzado":         "R1",
    "espiral":          "R12",
    "r12":              "R12",
    "msha":             "R12",        # cliente dice "msha" queriendo decir espiral MSHA
    "alta presion":     "4SH",
    "alta presión":     "4SH",
    "jack":             "JACK",
    "piloto":           "PILOT",
    "pilot":            "PILOT",
    "melliza":          "MELL",
    "mellizo":          "MELL",
    "oxi":              "MELL",
    "acetileno":        "MELL",
    "concreto":         "HCA",
    "hormigon":         "HCA",
    "matrix":           "MATRIX",
    "matrixflex":       "MATRIX",
    "alta temperatura": "HT",
    "alta temp":        "HT",
    "hightemp":         "HT",
    "ht":               "HT",
}

# ─── ALIAS DE COLOR/VARIANTE ──────────────────────────────────────────────────
COLOR_ALIAS = {
    "amarillo": "A",
    "negro":    "N",
    "rojo":     "R",
    "azul":     "S",    # algunos códigos usan S para azul/especial
    "epdm":     "EPDM",
}

# ─── PALABRAS IGNORADAS PARA DETECCIÓN DE CÓDIGO ──────────────────────────────
PALABRAS_IGNORADAS = {
    "hola", "buenas", "buenos", "precio", "stock", "cotiza", "cotización",
    "cotizacion", "necesito", "quiero", "tienen", "tengo", "dame", "manguera",
    "manga", "mang", "hidráulica", "hidraulica", "consulta", "ayuda", "dias",
    "días", "tardes", "noches", "gracias", "ok", "si", "sí", "no", "cuánto",
    "cuanto", "lista", "tipos", "hay", "cual", "cuales", "cuál",
}

# ─── CARGA DE DATOS ───────────────────────────────────────────────────────────
try:
    df = pd.read_excel(ruta_excel)
    df.columns = [c.strip() for c in df.columns]
    df["codigo"]      = df["Código"].astype(str).str.strip()
    df["marca"]       = df["Marca"].astype(str).str.strip().str.upper()
    df["descripcion"] = df["Descripción"].astype(str).str.strip().str.lower()
    df["precio"]      = pd.to_numeric(df["Precio Vta."], errors="coerce")
    df["unidad"]      = df["UND"].astype(str).str.strip()

    # Extraer tipo y medida del código
    # Patrón estándar: PREFIJO-TIPO-MEDIDA (ej: QF-R1-1/2", JDE-4SH-12)
    df["tipo_cod"]   = df["codigo"].str.extract(r'^[A-Z0-9]+-([A-Z0-9]+)-', expand=False).str.upper()
    df["medida_cod"] = df["codigo"].str.extract(r'^[A-Z0-9]+-[A-Z0-9]+-(.+)$', expand=False).str.strip()

    # Para códigos HYP con formato TFxxx-tipo-nominal, extraer igual
    # Ej: TFS0012-06 → tipo=R12 (inferido), nominal=06
    # Estos ya tienen tipo_cod y medida_cod extraídos correctamente por el regex

    df = df.dropna(subset=["codigo", "precio"])
    logger.info(f"Excel cargado: {len(df)} productos, {df['marca'].nunique()} marcas")
except Exception as e:
    logger.critical(f"ERROR CARGANDO EXCEL: {e}")
    raise

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _ruta_imagen(tipo_imagen: str):
    ruta = os.path.join(BASE_DIR, "data", "imagenes_productos", f"{tipo_imagen}.png")
    return ruta if os.path.exists(ruta) else None

def extraer_cantidad(texto: str) -> int:
    match = re.search(r"x\s*(\d+)", texto.lower())
    return int(match.group(1)) if match else 1

def extraer_descuento(texto: str) -> float:
    # Detecta: "descuento 20", "20%", "desc 20"
    m = re.search(r"descuento\s*(\d+)", texto.lower())
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d+)\s*%", texto)
    if m:
        return float(m.group(1))
    return 0.0

def normalizar_medida_texto(texto: str) -> str:
    """
    Convierte variantes que escribe el cliente a la medida estándar.
    Maneja: nominales (08→1/2), sin espacio (11/2→1 1/2), con punto (1.1/2→1 1/2).
    """
    t = texto.strip().lower()

    # Formato europeo con punto: 1.1/4 → 1 1/4
    t = re.sub(r'(\d+)\.(\d+/\d+)', r'\1 \2', t)

    # Sin espacio entre entero y fracción: 11/2 → 1 1/2, 21/4 → 2 1/4
    t = re.sub(r'\b(1)(1/4|1/2|3/4)\b', r'\1 \2', t)
    t = re.sub(r'\b(2)(1/2|1/4)\b', r'\1 \2', t)

    # Español
    sinonimos = {
        "un cuarto":        "1/4",   "tres dieciseisavos": "3/16",
        "cinco dieciseisavos": "5/16","tres octavos":       "3/8",
        "media":            "1/2",   "medio":              "1/2",
        "cinco octavos":    "5/8",   "tres cuartos":       "3/4",
        "siete octavos":    "7/8",   "una pulgada":        "1",
        "uno y cuarto":     "1 1/4", "uno y medio":        "1 1/2",
        "dos y medio":      "2 1/2", "dos pulgadas":       "2",
        "tres pulgadas":    "3",
    }
    for alias, val in sorted(sinonimos.items(), key=lambda x: len(x[0]), reverse=True):
        t = re.sub(rf'\b{re.escape(alias)}\b', val, t)

    # Guiones y variantes: 1-1/2 → 1 1/2
    t = re.sub(r'(\d+)-(\d+/\d+)', r'\1 \2', t)

    return t

# ─── FORMATEO ─────────────────────────────────────────────────────────────────

def formatear_resultado(fila, cantidad=1, descuento=0.0) -> str:
    precio   = float(fila["precio"])
    subtotal = precio * cantidad
    desc_monto = subtotal * (descuento / 100)
    total_final = subtotal - desc_monto
    resp = (
        f"✅ *{fila['codigo']}*\n"
        f"📋 {fila['descripcion'].title()}\n"
        f"🏷️ Marca: {fila['marca']}\n"
        f"💰 Precio: ${precio:.2f} x {fila['unidad']}\n"
    )
    if cantidad > 1:
        resp += f"📦 Cantidad: {cantidad}\n"
        resp += f"💵 Subtotal: ${subtotal:.2f}\n"
    if descuento > 0:
        resp += f"🏷️ Descuento: {descuento:.0f}% (-${desc_monto:.2f})\n"
        resp += f"💵 *Total: ${total_final:.2f}*\n"
    return resp

def formatear_lista(resultados: pd.DataFrame, titulo: str) -> str:
    """Lista de opciones — formato WhatsApp (sin bloques de código)."""
    resp = f"{titulo}\n\n"
    for _, fila in resultados.iterrows():
        resp += (
            f"• *{fila['codigo']}*\n"
            f"  {fila['descripcion'].title()[:50]}\n"
            f"  💰 ${float(fila['precio']):.2f}\n\n"
        )
    resp += "¿Cuál necesitas? Escríbeme el código exacto 👍"
    return resp

# ─── BÚSQUEDAS ────────────────────────────────────────────────────────────────

def buscar_por_codigo(codigo: str):
    """Búsqueda exacta por código (case-insensitive)."""
    r = df[df["codigo"].str.upper() == codigo.upper().strip()]
    return r.iloc[0] if not r.empty else None

def buscar_por_codigo_parcial(texto: str) -> pd.DataFrame:
    """Búsqueda por fragmento de código."""
    return df[df["codigo"].str.upper().str.contains(re.escape(texto.upper()), na=False)]

def buscar_por_tipo_medida_marca(tipo=None, medida=None, marca=None) -> pd.DataFrame:
    """Búsqueda flexible por tipo, medida y/o marca."""
    r = df.copy()
    if tipo:
        r = r[r["tipo_cod"].str.upper() == tipo.upper()]
    if marca:
        r = r[r["marca"].str.upper() == marca.upper()]
    if medida:
        # Match exacto: normalizar medida_cod y comparar
        # Ej: "1/2"" → "1/2", "1 1/2"" → "1 1/2" (sin comillas, sin espacios extra)
        medida_norm = medida.upper().strip().rstrip('"').strip()
        medida_cod_norm = r["medida_cod"].str.upper().str.strip().str.rstrip('"').str.strip()
        mascara = medida_cod_norm == medida_norm

        # Si no hay resultados, intentar también por nominal equivalente
        # (algunos códigos JDE/HYP guardan la medida como "08", "12", etc.)
        if not mascara.any():
            nominal_inv = {v: k for k, v in MEDIDA_NOMINAL.items()}
            nominal = nominal_inv.get(medida.strip().rstrip('"').strip())
            if nominal:
                mascara = r["medida_cod"].str.strip() == nominal
        r = r[mascara]
    return r

def buscar_por_descripcion(palabras: list) -> pd.DataFrame:
    """Búsqueda por palabras clave en descripción."""
    r = df.copy()
    for p in palabras:
        r = r[r["descripcion"].str.contains(re.escape(p.lower()), na=False)]
    return r

# ─── INTERPRETACIÓN DE LÍNEA ──────────────────────────────────────────────────

def interpretar_linea(texto: str) -> tuple:
    """
    Extrae (marca, tipo, medida, color, cantidad) del texto libre del cliente.
    """
    cantidad  = extraer_cantidad(texto)
    texto_lim = re.sub(r'x\s*\d+', '', texto).strip()
    texto_up  = texto_lim.upper()
    texto_lo  = normalizar_medida_texto(texto_lim.lower())

    # ── Marca ─────────────────────────────────────────────────────────────────
    marca = None
    for alias in sorted(MARCA_ALIAS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(alias)}\b', texto_lo):
            marca = MARCA_ALIAS[alias]
            break

    # ── Color/variante ────────────────────────────────────────────────────────
    color = None
    for alias, cod in sorted(COLOR_ALIAS.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf'\b{re.escape(alias)}\b', texto_lo):
            color = cod
            break

    # ── Tipo — primero sinónimos en español, luego tipos directos del catálogo
    tipo = None
    for alias in sorted(TIPO_ALIAS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(alias)}\b', texto_lo):
            tipo = TIPO_ALIAS[alias]
            break

    if not tipo:
        tipos_bd = sorted(df["tipo_cod"].dropna().unique().tolist(), key=len, reverse=True)
        for t in tipos_bd:
            if re.search(rf'\b{re.escape(t)}\b', texto_up):
                tipo = t
                break

    # ── Medida — buscar fracciones, enteros, nominales ────────────────────────
    medida = None

    # Medida compuesta: 1 1/2, 2 1/4, etc.
    m = re.search(r'\b(\d+\s+\d+/\d+)\b', texto_lo)
    if m:
        medida = m.group(1).strip()

    # Fracción simple: 3/4, 1/2, 5/16, etc.
    if not medida:
        m = re.search(r'\b(\d+/\d+)\b', texto_lo)
        if m:
            medida = m.group(1)

    # Entero con pulgadas explícitas: 1", 2"
    if not medida:
        m = re.search(r'\b(\d+)[""]', texto_lim)
        if m:
            medida = m.group(1)

    # Nominal de 2 dígitos: 08, 12, 16 (solo si parece nominal, no año u otro)
    if not medida:
        m = re.search(r'\b(0[2-9]|[1-6]\d)\b', texto_lo)
        if m and m.group(1) in MEDIDA_NOMINAL:
            medida = MEDIDA_NOMINAL[m.group(1)]
            logger.debug(f"  nominal '{m.group(1)}' → medida '{medida}'")

    # Entero solo (pulgadas sin símbolo): solo si hay contexto de tipo/marca
    if not medida and (tipo or marca):
        m = re.search(r'\b([1-4])\b', texto_lo)
        if m:
            medida = m.group(1)

    logger.debug(f"interpretar_linea → marca={marca} tipo={tipo} medida={medida} color={color} cant={cantidad}")
    return marca, tipo, medida, color, cantidad

# ─── CONSULTA SIMPLE ──────────────────────────────────────────────────────────

def consultar(texto: str) -> tuple:
    """
    Punto de entrada principal. Retorna (imagen, respuesta).
    """
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]

    # Cotización múltiple
    if len(lineas) > 1:
        logger.info(f"Cotización múltiple: {len(lineas)} líneas")
        return None, cotizar_multiple(lineas)

    texto = lineas[0]
    cantidad = extraer_cantidad(texto)
    descuento = extraer_descuento(texto)
    texto_sin_cant = re.sub(r'x\s*\d+', '', texto).strip()
    texto_sin_cant = re.sub(r'\b\d+\s*%', '', texto_sin_cant).strip()

    # ── Saludo / bienvenida ───────────────────────────────────────────────────
    SALUDOS = {"hola", "buenas", "buenos", "hi", "hello", "buenas noches",
               "buenas tardes", "buenas dias", "buenos dias", "buen dia",
               "buen día", "buenos días", "buenas noches", "saludos"}
    texto_norm = texto_sin_cant.lower().strip().rstrip("!.?,")
    if texto_norm in SALUDOS or all(p in PALABRAS_IGNORADAS for p in texto_norm.split()):
        logger.info("Saludo detectado — enviando bienvenida")
        return None, (
            "¡Hola! 👋 Soy el asistente de *CISGE*.\n\n"
            "Puedo ayudarte a cotizar mangueras hidráulicas al instante.\n\n"
            "Búscame por:\n"
            "• *Código:* QF-R1-1/2\"\n"
            "• *Tipo y medida:* R1 1/2 QF\n"
            "• *Descripción:* aire 1/2 negro\n"
            "• *Nominal:* R12 08 JDE\n\n"
            "Para cotizar varios productos a la vez, escribe uno por línea 📋\n\n"
            "¿Qué necesitas cotizar? 💬"
        )

    # ── Estrategia 1: código exacto ───────────────────────────────────────────
    fila = buscar_por_codigo(texto_sin_cant)
    if fila is not None:
        logger.info(f"Código exacto: {fila['codigo']}")
        log_consultas.append({"timestamp": datetime.now().isoformat(), "mensaje": texto, "tipo": "codigo_exacto"})
        tipo_cod = str(fila.get("tipo_cod", "") or "").lower()
        imagen = _ruta_imagen(tipo_cod)
        return imagen, formatear_resultado(fila, cantidad, descuento)

    # ── Estrategia 2: código parcial ──────────────────────────────────────────
    parcial = buscar_por_codigo_parcial(texto_sin_cant)
    if len(parcial) == 1:
        logger.info(f"Código parcial único: {parcial.iloc[0]['codigo']}")
        log_consultas.append({"timestamp": datetime.now().isoformat(), "mensaje": texto, "tipo": "codigo_parcial"})
        tipo_cod = str(parcial.iloc[0].get("tipo_cod", "") or "").lower()
        imagen = _ruta_imagen(tipo_cod)
        return imagen, formatear_resultado(parcial.iloc[0], cantidad, descuento)
    elif 1 < len(parcial) <= 10:
        return None, formatear_lista(parcial, f"Encontré {len(parcial)} productos similares:")

    # ── Estrategia 3: tipo + medida + marca + color ───────────────────────────
    marca, tipo, medida, color, cantidad = interpretar_linea(texto)

    if tipo or marca or medida:
        # Construir medida con color si aplica (ej: "1/2" N" → buscar "1/2" N")
        medida_busq = medida
        if color and medida:
            medida_busq = f'{medida}" {color}' if not medida.endswith('"') else f'{medida} {color}'

        resultados = buscar_por_tipo_medida_marca(tipo, medida_busq, marca)

        # Si con color no encontró, intentar sin color
        if resultados.empty and color and medida:
            resultados = buscar_por_tipo_medida_marca(tipo, medida, marca)

        if len(resultados) == 1:
            logger.info(f"Match por filtros: {resultados.iloc[0]['codigo']}")
            log_consultas.append({"timestamp": datetime.now().isoformat(), "mensaje": texto, "tipo": "filtros",
                                   "marca": marca, "tipo": tipo, "medida": medida})
            imagen = _ruta_imagen((tipo or "").lower())
            return imagen, formatear_resultado(resultados.iloc[0], cantidad, descuento)

        elif 1 < len(resultados) <= 12:
            return None, formatear_lista(resultados, f"Encontré {len(resultados)} opciones:")

        elif len(resultados) > 12:
            detalle = []
            if not marca:
                marcas = resultados["marca"].unique()
                detalle.append(f"🏷️ Marca: {', '.join(marcas)}")
            if not medida:
                meds = resultados["medida_cod"].dropna().unique()[:8]
                detalle.append(f"📐 Medida: {', '.join(meds)}")
            if not color:
                detalle.append("🎨 Color: Amarillo (A), Negro (N), Rojo (R)")
            return None, (
                f"Encontré *{len(resultados)} productos* para *{tipo or 'ese tipo'}*.\n\n"
                "¿Puedes especificar?\n\n" +
                "\n".join(detalle) +
                "\n\n_Ejemplo: R1 1/2 Negro QF_"
            )

    # ── Estrategia 4: palabras clave en descripción ───────────────────────────
    palabras = [p for p in texto_sin_cant.lower().split() if len(p) > 2
                and p not in PALABRAS_IGNORADAS]
    if palabras:
        resultados = buscar_por_descripcion(palabras)
        if len(resultados) == 1:
            return None, formatear_resultado(resultados.iloc[0], cantidad, descuento)
        elif 1 < len(resultados) <= 12:
            return None, formatear_lista(resultados, "Encontré estos productos:")

    # ── Sin resultados ────────────────────────────────────────────────────────
    log_consultas.append({"timestamp": datetime.now().isoformat(), "mensaje": texto, "tipo": "sin_resultado"})
    return None, (
        "No encontré ese producto 😕\n\n"
        "Puedes buscar por:\n"
        "• *Código exacto:* QF-R1-1/2\"\n"
        "• *Tipo y medida:* R1 1/2 QF\n"
        "• *Descripción:* aire 1/2 negro\n"
        "• *Nominal:* R12 08 JDE\n\n"
        "¿Cómo lo busco? 👍"
    )

# ─── COTIZACIÓN MÚLTIPLE ──────────────────────────────────────────────────────

def cotizar_multiple(lineas: list) -> str:
    respuesta    = "📋 *Cotización CISGE*\n─────────────────────\n\n"
    total        = 0.0
    descuento_pct = 0.0
    hay_error    = False

    for i, linea in enumerate(lineas, start=1):
        # Detectar línea de descuento
        if "descuento" in linea.lower():
            descuento_pct = extraer_descuento(linea)
            continue

        cantidad       = extraer_cantidad(linea)
        texto_sin_cant = re.sub(r'x\s*\d+', '', linea).strip()

        fila = None

        # 1. Código exacto
        fila = buscar_por_codigo(texto_sin_cant)

        # 2. Código parcial único
        if fila is None:
            parcial = buscar_por_codigo_parcial(texto_sin_cant)
            if len(parcial) == 1:
                fila = parcial.iloc[0]

        # 3. Tipo + medida + marca
        if fila is None:
            marca, tipo, medida, color, cantidad = interpretar_linea(linea)
            if tipo or marca or medida:
                medida_busq = medida
                if color and medida:
                    medida_busq = f'{medida}" {color}' if not medida.endswith('"') else f'{medida} {color}'
                resultados = buscar_por_tipo_medida_marca(tipo, medida_busq, marca)
                if resultados.empty and color:
                    resultados = buscar_por_tipo_medida_marca(tipo, medida, marca)
                if len(resultados) == 1:
                    fila = resultados.iloc[0]

        if fila is not None:
            precio   = float(fila["precio"])
            subtotal = precio * cantidad
            total   += subtotal
            desc     = fila['descripcion'].title()[:45]
            respuesta += (
                f"{i}️⃣ *{fila['codigo']}* — {desc}\n"
                f"   x{cantidad} × ${precio:.2f} = *${subtotal:.2f}*\n\n"
            )
        else:
            respuesta += f"{i}️⃣ ❌ _{linea}_\n\n"
            hay_error = True

    descuento_monto = total * (descuento_pct / 100)
    total_final     = total - descuento_monto

    respuesta += "─────────────────────\n"
    if descuento_pct > 0:
        respuesta += f"Subtotal: ${total:.2f}\n"
        respuesta += f"Descuento ({descuento_pct:.0f}%): -${descuento_monto:.2f}\n"
    respuesta += f"💵 *TOTAL: ${total_final:.2f}*"

    if hay_error:
        respuesta += "\n\n_(*) Algunos ítems no encontrados. Escríbeme para revisar._"

    log_consultas.append({
        "timestamp": datetime.now().isoformat(),
        "tipo": "multiple",
        "lineas": len(lineas),
        "total": total_final,
    })
    return respuesta
