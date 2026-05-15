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
    "lisa":             "R1S",
    "smooth":           "R1S",
    "r1s":              "R1S",
    "r1 s":             "R1S",
    "r2s":              "R2S",
    "r2 s":             "R2S",
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
    # VITILLO Everest isobárica (producto distinto al R15)
    "tser":             "TSER",
    "everest":          "TSER",
    "4000 psi":         "TSER",
    "4000psi":          "TSER",
    "5000 psi":         "TSER",
    "5000psi":          "TSER",
    "6000 psi":         "TSER",
    "6000psi":          "TSER",
    # Estándares SAE/ISO hidráulicos
    "r1":               "R1",
    "r2":               "R2",
    "r3":               "R3",
    "r4":               "R4",
    "r5":               "R5",
    "r6":               "R6",
    "r7":               "R7",
    "r9":               "R9",
    "r13":              "R13",
    "r15":              "R15",  # R15 SAE → TSR15xx (no confundir con TSER/Everest)
    "4sh":              "4SH",
    "4sp":              "4SP",
    "2sn":              "R2",   # alias común en campo
    "1sn":              "R1",   # alias común en campo
}

# Tipos SAE que pueden tener múltiples tipo_cod en BD
# (cuando un tipo SAE corresponde a varios códigos de proveedor)
TIPO_SAE_MAP = {
    "R1":  ["R1", "TH"],       # R1 puede ser R1 (QF/JDE) o TH (VITILLO)
    "R2":  ["R2", "TH"],       # R2 también en TH de VITILLO
    "R12": ["R12", "TSR"],     # R12 puede ser R12 o TSR (VITILLO TSR12xx)
    "R13": ["TSR"],            # R13 = TSR (VITILLO TSR13xx)
    "R15": ["R15", "TSR"],     # R15 directo (JDE/QF) y TSR15xx (VITILLO)
    "4SH": ["4SH", "TS"],      # 4SH puede ser 4SH o TS (VITILLO Teknospir)
    "4SP": ["4SP", "TS"],      # 4SP también en TS de VITILLO
    "R4":  ["R"],              # R4 usa prefijo R en AF
    "R6":  ["R"],              # R6 también usa prefijo R en AF
}

# ─── LÍNEAS PREMIUM (modificadores, no tipos) ───────────────────────────────
# Estas líneas son versiones mejoradas que aplican a múltiples tipos SAE
LINEA_ALIAS = {
    "exactflex":   "exact",
    "exact flex":  "exact",
    "shieldflex":  "shield",
    "shield flex": "shield",
    "shield":      "shield",
    "teknospir":   "teknospir",
    "tekno":       "tekno",
}

# ─── ALIAS DE COLOR/VARIANTE ──────────────────────────────────────────────────
COLOR_ALIAS = {
    "amarillo": "A",
    "negro":    "N",
    "rojo":     "R",
    "azul":     "S",    # algunos códigos usan S para azul/especial
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
    df["precio"]      = pd.to_numeric(df["Valor Vta."], errors="coerce")
    df["unidad"]      = df["UND"].astype(str).str.strip()

    # Extraer tipo y medida del código
    # Patrón estándar: PREFIJO-TIPO-MEDIDA (ej: QF-R1-1/2", JDE-4SH-12)
    # También captura PREFIJO-TIPOMED (ej: VT-TSER420)
    df["tipo_cod"]   = df["codigo"].str.extract(r'^[A-Z0-9]+-([A-Z]+\d*[A-Z]*)', expand=False).str.upper()
    df["medida_cod"] = df["codigo"].str.extract(r'^[A-Z0-9]+-[A-Z0-9]+-(.+)$', expand=False).str.strip()

    # Para VITILLO TSER/EVEREST: extraer medida de la descripción
    mask_tser = df["tipo_cod"].str.startswith("TSER", na=False) & df["medida_cod"].isna()
    df.loc[mask_tser, "medida_cod"] = df.loc[mask_tser, "descripcion"].str.extract(
        r'(\d+\s*\d*/\d+\"?|\d+\")', expand=False
    ).str.strip()

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

def buscar_por_tipo_medida_marca(tipo=None, medida=None, marca=None, presion=None, linea=None, subtipo=None) -> pd.DataFrame:
    """Búsqueda flexible por tipo, medida y/o marca."""
    r = df.copy()
    if tipo:
        tipo_up = tipo.upper()
        # Verificar si hay múltiples tipo_cod posibles para este tipo SAE
        tipos_posibles = TIPO_SAE_MAP.get(tipo_up, [tipo_up])
        mascara_tipo = r["tipo_cod"].str.upper().isin(tipos_posibles)
        # Para tipos que comparten tipo_cod TSR (R12/R13/R15) o R (R4/R6):
        # filtrar también por descripción
        if tipo_up in ("R4", "R6", "R13"):
            mascara_tipo = mascara_tipo & r["descripcion"].str.contains(tipo_up, na=False, case=False)
        elif tipo_up == "R15":
            # R15 directo ya está correcto; TSR necesita filtrar por descripción
            mascara_tsr15 = (r["tipo_cod"].str.upper() == "TSR") & r["descripcion"].str.contains("R15", na=False, case=False)
            mascara_r15_directo = r["tipo_cod"].str.upper() == "R15"
            mascara_tipo = mascara_r15_directo | mascara_tsr15
        elif tipo_up == "R12":
            # R12 puede estar en tipo_cod R12 directo O en TSR12xx
            mascara_tsr12 = r["tipo_cod"].str.upper() == "TSR"
            mascara_tsr12 = mascara_tsr12 & r["descripcion"].str.contains("R12", na=False, case=False)
            mascara_r12_directo = r["tipo_cod"].str.upper() == "R12"
            mascara_tipo = mascara_r12_directo | mascara_tsr12
        r = r[mascara_tipo]
    if linea:
        r = r[r["descripcion"].str.contains(linea, na=False, case=False)]
    if subtipo and subtipo in ("1SN", "2SN"):
        r = r[r["medida_cod"].str.upper().str.startswith(subtipo, na=False)]
    if presion:
        r = r[r["descripcion"].str.contains(str(presion), na=False, case=False)]
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
    Extrae (marca, tipo, medida, color, cantidad, presion) del texto libre del cliente.
    """
    cantidad  = extraer_cantidad(texto)
    texto_lim = re.sub(r'x\s*\d+', '', texto).strip()
    texto_up  = texto_lim.upper()
    texto_lo  = normalizar_medida_texto(texto_lim.lower())

    # ── Línea premium (exactflex, shieldflex, teknospir) ──────────────────────
    linea = None
    for alias in sorted(LINEA_ALIAS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(alias)}\b', texto_lo):
            linea = LINEA_ALIAS[alias]
            break

    # ── Presión (para mangueras TSER/Everest) ────────────────────────────────
    presion = None
    m_psi = re.search(r'\b(\d{4})\s*(?:psi)?\b', texto_lo)
    if m_psi and m_psi.group(1) in ("4000", "5000", "6000"):
        presion = m_psi.group(1)

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
    # Detectar letra de color sola al final: "air 1/2 a", "air 1/2 n", "air 1/2 r"
    color_de_letra_s = False
    if not color:
        # Detectar letra de color sola: al final o antes de epdm
        # Remover epdm para encontrar la letra
        texto_sin_epdm = re.sub(r'\bepdm\b', '', texto_lo).strip()
        m = re.search(r'\b([anrs])\s*$', texto_sin_epdm.rstrip())
        if m:
            letra = m.group(1).upper()
            mapa = {"A": "A", "N": "N", "R": "R", "S": "S"}
            color = mapa.get(letra)
            if letra == "S":
                color_de_letra_s = True

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
    # Excluir números seguidos de % (descuentos)
    if not medida:
        texto_sin_pct = re.sub(r'\d+\s*%', '', texto_lo)
        m = re.search(r'\b(0[2-9]|[1-6]\d)\b', texto_sin_pct)
        if m and m.group(1) in MEDIDA_NOMINAL:
            medida = MEDIDA_NOMINAL[m.group(1)]
            logger.debug(f"  nominal '{m.group(1)}' → medida '{medida}'")

    # Entero solo (pulgadas sin símbolo): solo si hay contexto de tipo/marca
    if not medida and (tipo or marca):
        m = re.search(r'\b([1-4])\b', texto_lo)
        if m:
            medida = m.group(1)

    # "s" letra suelta + tipo R1/R2 = smooth (cubierta lisa), no color azul
    if color_de_letra_s and tipo in ("R1", "R2"):
        tipo = tipo + "S"
        color = None

    logger.debug(f"interpretar_linea → marca={marca} tipo={tipo} medida={medida} color={color} cant={cantidad} presion={presion} linea={linea}")
    return marca, tipo, medida, color, cantidad, presion, linea

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
    marca, tipo, medida, color, cantidad, presion, linea = interpretar_linea(texto)
    logger.info(f"E3 → marca={marca} tipo={tipo} medida={medida} linea={linea} presion={presion}")

    # Líneas exclusivas → forzar marca automáticamente
    if linea == "exact":
        marca = "JDEFLEX"
    # Everest es exclusivo de VITILLO (ya mapeado a TSER en TIPO_ALIAS)
    if tipo == "TSER" and not marca:
        marca = "VITILLO"

    # Si hay línea premium pero no tipo → pedir el tipo
    if linea and not tipo:
        nombre_linea = {"exact": "Exact Flex", "shield": "Shield Flex", "teknospir": "TeknoSpir", "tekno": "Tekno"}.get(linea, linea.title())
        return None, (
            f"Entendido, quieres la línea *{nombre_linea}* 👍\n\n"
            "¿Qué tipo de manguera necesitas?\n"
            "• R1, R2, R3, R4, R5, R6, R7\n"
            "• R12, R13, R15\n"
            "• 4SH, 4SP"
        )

    if tipo or marca or medida:
        # Construir medida con color si aplica (ej: "1/2" N" → buscar "1/2" N")
        medida_busq = medida
        # Detectar EPDM como modificador adicional
        epdm = "EPDM" if re.search(r'\bepdm\b', texto.lower()) else ""
        if color and medida:
            base = f'{medida}" {color}' if not medida.endswith('"') else f'{medida} {color}'
            medida_busq = f'{base} {epdm}'.strip() if epdm and epdm not in base else base

        # Llamada principal con medida_busq (incluye color y EPDM)
        subtipo_ht = color if tipo == 'HT' else None
        resultados = buscar_por_tipo_medida_marca(tipo, medida_busq, marca, presion, linea, subtipo_ht)

        # Si no encontró, intentar sin color/EPDM
        if resultados.empty and color and medida:
            resultados = buscar_por_tipo_medida_marca(tipo, medida, marca, presion, linea, subtipo_ht)

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
    respuesta     = "📋 *Cotización CISGE*\n─────────────────────\n\n"
    subtotal_bruto = 0.0
    total_descuentos = 0.0
    descuento_global = 0.0
    hay_error     = False

    for i, linea in enumerate(lineas, start=1):
        # Detectar línea de descuento global
        if "descuento" in linea.lower() and not re.search(r'x\s*\d+', linea.lower()):
            descuento_global = extraer_descuento(linea)
            continue

        cantidad       = extraer_cantidad(linea)
        desc_linea     = extraer_descuento(linea)
        texto_sin_cant = re.sub(r'x\s*\d+', '', linea).strip()
        texto_sin_cant = re.sub(r'\b\d+\s*%', '', texto_sin_cant).strip()

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
            marca, tipo, medida, color, cantidad, presion, linea_prem = interpretar_linea(linea)
            if tipo or marca or medida:
                medida_busq = medida
                if color and medida:
                    medida_busq = f'{medida}" {color}' if not medida.endswith('"') else f'{medida} {color}'
                resultados = buscar_por_tipo_medida_marca(tipo, medida_busq, marca, presion, linea_prem)
                if resultados.empty and color:
                    resultados = buscar_por_tipo_medida_marca(tipo, medida, marca, presion, linea_prem)
                if len(resultados) == 1:
                    fila = resultados.iloc[0]

        if fila is not None:
            precio      = float(fila["precio"])
            subtotal    = precio * cantidad
            pct         = desc_linea
            desc_monto  = subtotal * (pct / 100)
            subtotal_bruto   += subtotal
            total_descuentos += desc_monto
            desc_txt    = fila['descripcion'].title()[:45]
            linea_resp  = (
                f"{i}️⃣ *{fila['codigo']}* — {desc_txt}\n"
                f"   x{cantidad} × ${precio:.2f} | Subtotal: ${subtotal:.2f}"
            )
            if pct > 0:
                linea_resp += f" | Desc {pct:.0f}%: -${desc_monto:.2f}"
            respuesta += linea_resp + "\n\n"
        else:
            respuesta += f"{i}️⃣ ❌ _{linea}_\n\n"
            hay_error = True

    # Descuento global sobre el subtotal neto
    subtotal_neto   = subtotal_bruto - total_descuentos
    desc_global_monto = subtotal_neto * (descuento_global / 100)
    total_final     = subtotal_neto - desc_global_monto
    total_descuentos += desc_global_monto

    respuesta += "─────────────────────\n"
    respuesta += f"Subtotal:    ${subtotal_bruto:.2f}\n"
    if total_descuentos > 0:
        respuesta += f"Descuentos:  -${total_descuentos:.2f}\n"
    respuesta += f"💵 *TOTAL:   ${total_final:.2f}*"

    if hay_error:
        respuesta += "\n\n_(*) Algunos ítems no encontrados. Escríbeme para revisar._"

    log_consultas.append({
        "timestamp": datetime.now().isoformat(),
        "tipo": "multiple",
        "lineas": len(lineas),
        "total": total_final,
    })
    return respuesta
