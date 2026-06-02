import asyncio
import os
import re
import logging
import time
import httpx
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

# ─── RUTAS / API ──────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_URL  = "https://api.comercialcisgesac.com.pe/stock"

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

# ─── SUBFAMILIAS (categorías del ERP) ────────────────────────────────────────
SUBFAMILIA_MAP = {
    "adaptador":  ["ADAPTADORES I", "ADAPTADORES II"],
    "adap":       ["ADAPTADORES I", "ADAPTADORES II"],
    "espiga":     ["ESPIGAS I", "ESPIGAS II"],
    "manguera":   ["MANGUERAS HIDRAULICAS", "MANGUERAS INDUSTRIALES"],
    "mang":       ["MANGUERAS HIDRAULICAS", "MANGUERAS INDUSTRIALES"],
    "brida":      ["BRIDAS"],
    "camlock":    ["CAMLOCK"],
    "ferrula":    ["FERRULAS"],
    "férrula":    ["FERRULAS"],
    "valvula":    ["VALVULAS"],
    "válvula":    ["VALVULAS"],
    "acople":     ["ACOPLE RAPIDO", "ACOPLE GARRA", "ACOPLE DIAGNÓSTICO"],
    "prearmada":  ["PREARMADAS"],
    "niple":      ["NIPLES"],
    "tuberia":    ["TUBERIAS HIDRAULICAS"],
    "tubo":       ["TUBERIAS HIDRAULICAS"],
    "manometro":  ["MANOMETROS"],
    "manómetro":  ["MANOMETROS"],
    "protector":  ["PROTECTORES DE MANGUERAS"],
    "abrazadera": ["ABRAZADERAS", "ABRAZADERAS DE TUBOS"],
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
    "succión":              "SW",
    "succion agua":         "SW",
    "succion de agua":      "SW",
    "succion oil":          "SG",
    "succión oil":          "SG",
    "succion aceite":       "SG",
    "succion de aceite":    "SG",
    "descarga agua":        "DW",
    "descarga de agua":     "DW",
    "discharge water":      "DW",
    "dw":                   "DW",
    "descarga aceite":      "DG",
    "descarga de aceite":   "DG",
    "discharge oil":        "DG",
    "descarga oil":         "DG",
    "dg":                   "DG",
    "multipropósito":   "MP",
    "multiproposito":   "MP",
    "multipropocito":   "MP",
    "multiprop":        "MP",
    "carwash":          "R2CW",
    "car wash":         "R2CW",
    "lavado auto":      "R2CW",
    "lavado":           "R2CW",
    "r1s":              "R1S",
    "r1 s":             "R1S",
    "r2s":              "R2S",
    "r2 s":             "R2S",
    "trenzada":         "R1",
    "trenzado":         "R1",
    "espiral":          "R12",
    "r12":              "R12",

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
    "celsius":          "HT",
    "a/temp":           "HT",
    "a/t":              "HT",
    # VITILLO Everest isobárica (producto distinto al R15)
    # Nota: "4000psi"/"5000psi"/"6000psi" ya NO van aquí — los maneja
    # la detección de presión para incluir también JDE MatrixFlex
    "tser":             "TSER",
    "everest":          "TSER",
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
    "4she":             "4SHE",
    "4sp":              "4SP",
    "4spe":             "4SPE",
    "2sn":              "R2",   # alias común en campo
    "1sn":              "R1",   # alias común en campo
}

# Tipos SAE que pueden tener múltiples tipo_cod en BD
# (cuando un tipo SAE corresponde a varios códigos de proveedor)
TIPO_SAE_MAP = {
    "R1":  ["R1"],
    "R2":  ["R2"],
    "R12": ["R12"],
    "R13": ["R13"],
    "R15": ["R15"],
    "4SH": ["4SH", "4SHE"],   # 4SHE = JDE ExactFlex
    "4SP": ["4SP", "4SPE"],   # 4SPE = JDE ExactFlex
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

# ─── SUPERFICIE DE CUBIERTA (modificador, no tipo) ────────────────────────────
SUPERFICIE_ALIAS = {
    "corrugada":  "corrugada",
    "corrugado":  "corrugada",
    "corg":       "corrugada",
    "lisa":       "lisa",
    "smooth":     "lisa",    # smooth = lisa en cubierta de R14/otros tipos
}

# ─── ALIAS DE COLOR/VARIANTE ──────────────────────────────────────────────────
COLOR_ALIAS = {
    "amarillo": "A",
    "amarilla": "A",
    "negro":    "N",
    "negra":    "N",
    "rojo":     "R",
    "roja":     "R",
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

# ─── CARGA DE DATOS DESDE API ────────────────────────────────────────────────

_api_data: dict = {}        # caché completo del último fetch exitoso
_aliases_marcas: dict = {}  # {alias_lower: nombre_oficial} cargado desde /marcas

MARCAS_API_URL = "https://api.comercialcisgesac.com.pe/marcas"


def cargar_aliases_marcas() -> dict:
    """Carga aliases de marcas desde la API interna. Devuelve {} si falla."""
    try:
        r = httpx.get(MARCAS_API_URL, timeout=5)
        r.raise_for_status()
        data = r.json()
        # Espera {alias: nombre_oficial} o lista de {alias, nombre}
        if isinstance(data, dict):
            return {k.lower(): v.upper() for k, v in data.items()}
        if isinstance(data, list):
            return {item["alias"].lower(): item["nombre"].upper() for item in data
                    if "alias" in item and "nombre" in item}
    except Exception as e:
        logger.warning(f"cargar_aliases_marcas falló: {e}")
    return {}


def _build_df_from_api(data: dict) -> pd.DataFrame:
    """Construye el DataFrame de búsqueda desde la respuesta de la API.
    Cada elemento de 'productos' es una fila; el mismo codigo puede aparecer
    varias veces con distinta marca (multi-marca). El campo 'almacenes' se
    guarda directamente en el DataFrame para no necesitar índice secundario.
    """
    _COLS = ["codigo", "codigo_interno", "descripcion", "marca",
             "precio", "unidad", "almacenes", "subfamilia", "grupo",
             "tipo_cod", "medida_cod"]
    _EMPTY = pd.DataFrame(columns=_COLS)
    productos = data.get("productos", [])
    if not productos:
        return _EMPTY

    rows = [
        {
            "codigo":         str(p.get("codigo", "")).strip(),
            "codigo_interno": str(p.get("codigo_interno", "")).strip(),
            "descripcion":    str(p.get("descripcion", "")).strip().lower(),
            "marca":          str(p.get("marca", "")).strip().upper(),
            "precio":         p.get("precio"),
            "unidad":         str(p.get("unidad", "")).strip(),
            "almacenes":      p.get("almacenes") or {},
            "subfamilia":     str(p.get("subfamilia", "")).strip().upper(),
            "grupo":          str(p.get("grupo", "")).strip().upper(),
        }
        for p in productos
        if str(p.get("codigo", "")).strip()
    ]
    df_new = pd.DataFrame(rows)
    df_new["precio"] = pd.to_numeric(df_new["precio"], errors="coerce")

    # Extraer tipo y medida del código
    df_new["tipo_cod"]   = df_new["codigo"].str.extract(r'^[A-Z0-9]+-([A-Z0-9]*[A-Z][A-Z0-9]*)', expand=False).str.upper()
    df_new["medida_cod"] = df_new["codigo"].str.extract(r'^[A-Z0-9]+-[A-Z0-9]+-(.+)$', expand=False).str.strip()

    def _extraer_medidas_lista(codigo: str) -> list:
        """Extrae todas las medidas nominales del código como lista ordenada."""
        segmentos = re.findall(r'(?<![A-Z])(\d{2})(?![A-Z\d])', codigo.upper())
        return [MEDIDA_NOMINAL[s] for s in segmentos if s in MEDIDA_NOMINAL]

    df_new["medidas_cod"] = df_new["codigo"].apply(_extraer_medidas_lista)

    # Para VITILLO TSER/EVEREST: extraer medida de la descripción
    mask_tser = df_new["tipo_cod"].str.startswith("TSER", na=False) & df_new["medida_cod"].isna()
    df_new.loc[mask_tser, "medida_cod"] = df_new.loc[mask_tser, "descripcion"].str.extract(
        r'(\d+\s*\d*/\d+\"?|\d+\")', expand=False
    ).str.strip()

    # tipo_cod desde descripción: solo HYP (evita falsos positivos en accesorios
    # de otras marcas cuyos nombres contienen "1sn", "2sn", "r1at", etc.)
    mask_hyp = df_new["tipo_cod"].isna() & (df_new["marca"] == "HYP")
    if mask_hyp.any():
        for pat, tipo in [
            (r'\bcelsius\b|\ba/temp\b',  'HT'),   # antes que R1/R2
            (r'\br12\b',                 'R12'),
            (r'\br13\b',                 'R13'),
            (r'\br15\b',                 'R15'),
            (r'\b4sh\b',                 '4SH'),
            (r'\b4sp\b',                 '4SP'),
            (r'\br9\b',                  'R9'),
            (r'\br7\b',                  'R7'),
            (r'\br1at\b|\b1sn\b',        'R1'),
            (r'\br2at\b|\b2sn\b',        'R2'),
            (r'\b1sc\b',                 '1SC'),
            (r'\b2sc\b',                 '2SC'),
        ]:
            aplica = mask_hyp & df_new["descripcion"].str.contains(pat, na=False, case=False) & df_new["tipo_cod"].isna()
            df_new.loc[aplica, "tipo_cod"] = tipo
        n_hyp = int((df_new["marca"] == "HYP").sum())
        logger.info(f"HYP: tipo inferido en {n_hyp} filas")

    # medida_cod desde nominal al final del código: aplica a todos los NaN
    # (cubre VITILLO 2-segmentos VT-TH1SN08→"08"→"1/2", HYP TFDH011B08→"08"→"1/2", etc.)
    mask_med_nan = df_new["medida_cod"].isna()
    if mask_med_nan.any():
        cod_limpio = df_new.loc[mask_med_nan, "codigo"].str.upper().str.replace(r'\(PROM\)', '', regex=True).str.strip()
        nom = cod_limpio.str.extract(r'(\d{2})(?:[A-Z]{1,3})?$', expand=False)
        df_new.loc[mask_med_nan, "medida_cod"] = nom.map(lambda x: MEDIDA_NOMINAL.get(str(x)) if pd.notna(x) else None)

    # VITILLO: normalizar tipo_cod (TH1SN08 → R1, TH2SN08 → R2, TSR1208 → R12, etc.)
    mask_vt = df_new["marca"] == "VITILLO"
    vt_tipo = df_new.loc[mask_vt, "tipo_cod"].str.upper().fillna("")
    for prefix, norm in [
        ("TH1SN", "R1"),
        ("TH2SN", "R2"),
        ("TH2SC", "2SC"),
        ("TS4SH", "4SH"),
        ("TS4SP", "4SP"),
        ("TSR12", "R12"),
        ("TSR13", "R13"),
        ("TSR15", "R15"),
    ]:
        df_new.loc[mask_vt & vt_tipo.str.startswith(prefix), "tipo_cod"] = norm
    logger.info(f"VITILLO: tipo_cod normalizado en {mask_vt.sum()} filas")

    # R4/R6 mal clasificados en el ERP — corregir subfamilia
    mask_r4r6 = df_new["grupo"].isin(["R4", "R6"])
    df_new.loc[mask_r4r6, "subfamilia"] = "MANGUERAS HIDRAULICAS"

    df_new = df_new.dropna(subset=["codigo", "precio"])
    return df_new


def _load_api_sync() -> dict:
    """Carga inicial sincrónica con 3 reintentos. Devuelve dict vacío si falla."""
    for attempt in range(3):
        try:
            r = httpx.get(API_URL, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"API intento {attempt + 1}/3 fallido: {e}")
            if attempt < 2:
                time.sleep(2)
    return {}


# Carga inicial al arrancar
_api_data = _load_api_sync()
df = _build_df_from_api(_api_data)
if df.empty:
    logger.critical("No se pudo cargar datos desde la API al arrancar — df vacío")
else:
    logger.info(f"API cargada: {len(df)} productos, {df['marca'].nunique()} marcas, actualizado: {_api_data.get('actualizado', 'N/D')}")

_aliases_marcas = cargar_aliases_marcas()
logger.info(f"Aliases de marcas cargados: {len(_aliases_marcas)} entradas")


async def refresh_stock_loop():
    """Refresca la caché de la API y los aliases de marcas cada 10 minutos."""
    global _api_data, df, _aliases_marcas
    while True:
        await asyncio.sleep(600)
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(API_URL, timeout=30)
                r.raise_for_status()
                data = r.json()
            _api_data = data
            df = _build_df_from_api(data)
            logger.info(f"API refrescada: {len(df)} productos, actualizado: {data.get('actualizado', 'N/D')}")
        except Exception as e:
            logger.warning(f"Error refrescando API: {e} — manteniendo datos anteriores")
        nuevos = cargar_aliases_marcas()
        if nuevos:
            _aliases_marcas = nuevos
            logger.info(f"Aliases de marcas refrescados: {len(_aliases_marcas)} entradas")


def _stock_total(fila) -> float:
    """Suma el stock de todos los almacenes de una fila del DataFrame."""
    alm = fila["almacenes"] if isinstance(fila["almacenes"], dict) else {}
    return sum(alm.values())

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _ruta_imagen(tipo_imagen: str):
    ruta = os.path.join(BASE_DIR, "data", "imagenes_productos", f"{tipo_imagen}.png")
    return ruta if os.path.exists(ruta) else None

def extraer_cantidad(texto: str) -> int:
    match = re.search(r"\bx\s*(\d+)", texto.lower())
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

IGV = 0.18

def formatear_resultado(fila, cantidad=1, descuento=0.0) -> str:
    precio   = float(fila["precio"])
    subtotal = precio * cantidad
    desc_monto = subtotal * (descuento / 100)
    total_final = subtotal - desc_monto
    total_igv   = total_final * (1 + IGV)

    total_stock = _stock_total(fila)
    agotado = (total_stock == 0)
    almacenes_raw = fila["almacenes"] if isinstance(fila["almacenes"], dict) else {}

    icono = "⚠️" if agotado else "✅"
    resp = (
        f"{icono} *{fila['codigo']}*\n"
        f"📋 {fila['descripcion'].title()}\n"
        f"🏷️ Marca: {fila['marca']}\n"
        f"💰 Precio: ${precio:.2f} x {fila['unidad']}\n"
    )
    if cantidad > 1:
        resp += f"📦 Cantidad: {cantidad}\n"
        resp += f"💵 Subtotal: ${subtotal:.2f}\n"
    if descuento > 0:
        resp += f"🏷️ Descuento: {descuento:.0f}% (-${desc_monto:.2f})\n"
        resp += f"💵 Total s/IGV: ${total_final:.2f}\n"
    resp += f"🧾 *Total c/IGV: ${total_igv:.2f}*\n"

    if not almacenes_raw:
        resp += "⚠️ Sin stock registrado\n"
    elif agotado:
        resp += "🚫 *AGOTADO* — sin stock disponible actualmente\n"
    else:
        umed = fila["unidad"]
        almacenes = {a: c for a, c in almacenes_raw.items() if c > 0}
        if len(almacenes) == 1:
            alm, cant = next(iter(almacenes.items()))
            resp += f"📦 Stock: {cant:.2f} {umed} ({alm})\n"
        else:
            resp += "📦 Stock:\n"
            for alm, cant in almacenes.items():
                resp += f"  • {alm}: {cant:.2f} {umed}\n"

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

def formatear_multi_marca(resultados: pd.DataFrame) -> str:
    """Muestra las variantes de marca para un mismo código comercial."""
    primera = resultados.iloc[0]
    codigo = primera["codigo"]
    descr  = primera["descripcion"].title()[:60]
    resp   = f"📋 *{codigo}*\n{descr}\n\n"

    for i, (_, fila) in enumerate(resultados.iterrows(), start=1):
        total  = _stock_total(fila)
        precio = float(fila["precio"])
        marca  = fila["marca"]
        umed   = fila["unidad"]

        if total == 0:
            stock_txt = "🚫 AGOTADO"
        else:
            alm_con_stock = {a: c for a, c in fila["almacenes"].items() if c > 0}
            partes = [f"{a.replace('Almacen ', '')}: {c:.0f}" for a, c in alm_con_stock.items()]
            stock_txt = f"📦 {' | '.join(partes)} {umed}"

        resp += f"{i}️⃣ *{marca}*  →  ${precio:.2f} x {umed}\n   {stock_txt}\n\n"

    resp += f"_Para cotizar escribe: {codigo} + marca_\n"
    resp += f"_Ej: {codigo} {primera['marca']}_"
    return resp

# ─── BÚSQUEDAS ────────────────────────────────────────────────────────────────

def buscar_por_codigo(codigo: str) -> pd.DataFrame:
    """Búsqueda exacta por código (case-insensitive). Devuelve DataFrame (puede ser multi-marca)."""
    return df[df["codigo"].str.upper() == codigo.upper().strip()]

def buscar_por_codigo_prefijo(texto: str) -> pd.DataFrame:
    """Búsqueda por prefijo de código (case-insensitive)."""
    return df[df["codigo"].str.upper().str.startswith(texto.upper().strip(), na=False)]

def buscar_por_tipo_medida_marca(tipo=None, medida=None, marca=None, presion=None, linea=None, subtipo=None, superficie=None, subfamilias=None, medidas=None) -> pd.DataFrame:
    """Búsqueda flexible por tipo, medida y/o marca."""
    r = df.copy()
    medidas_aplicadas = False
    if subfamilias:
        r = r[r["subfamilia"].isin(subfamilias)]
    if tipo:
        tipo_up = tipo.upper()
        # Intento 1: match exacto por grupo (campo directo del ERP)
        mask_grupo = r["grupo"].str.upper() == tipo_up
        if mask_grupo.any():
            r = r[mask_grupo]
        else:
            # Fallback: lógica anterior por tipo_cod
            tipos_posibles = TIPO_SAE_MAP.get(tipo_up, [tipo_up])
            mascara_tipo = r["tipo_cod"].str.upper().isin(tipos_posibles)
            if tipo_up in ("R4", "R6", "R13"):
                mascara_tipo = mascara_tipo & r["descripcion"].str.contains(tipo_up, na=False, case=False)
            elif tipo_up == "R15":
                mascara_tsr15 = (r["tipo_cod"].str.upper() == "TSR") & r["descripcion"].str.contains("R15", na=False, case=False)
                mascara_r15_directo = r["tipo_cod"].str.upper() == "R15"
                mascara_tipo = mascara_r15_directo | mascara_tsr15
            elif tipo_up == "R12":
                mascara_tsr12 = (r["tipo_cod"].str.upper() == "TSR") & r["descripcion"].str.contains("R12", na=False, case=False)
                mascara_r12_directo = r["tipo_cod"].str.upper() == "R12"
                mascara_tipo = mascara_r12_directo | mascara_tsr12
            elif tipo_up == "TSER":
                mascara_tipo = r["tipo_cod"].str.upper().str.startswith("TSER", na=False)
            r = r[mascara_tipo]
    if linea:
        r = r[r["descripcion"].str.contains(linea, na=False, case=False)]
    if subtipo and subtipo in ("1SN", "2SN"):
        r = r[r["medida_cod"].str.upper().str.startswith(subtipo, na=False)]
    if presion:
        psi_str = str(presion)              # "4000", "5000", "6000"
        k_str   = psi_str[0] + "K"         # "4K",   "5K",   "6K"
        mascara_pres = (
            r["descripcion"].str.contains(psi_str, na=False, case=False) |
            r["descripcion"].str.contains(k_str,   na=False, case=False) |
            r["medida_cod"].str.upper().str.contains(k_str, na=False)
        )
        r = r[mascara_pres]
    if marca:
        r = r[r["marca"].str.upper() == marca.upper()]
    # Filtro de superficie: corrugada filtra por descripción; lisa excluye corrugadas
    if superficie == "corrugada":
        r = r[r["descripcion"].str.contains("corrugada", na=False, case=False)]
    elif superficie == "lisa":
        r = r[~r["descripcion"].str.contains("corrugada", na=False, case=False)]
    if medidas and not medidas_aplicadas:
        subfams_actuales = set(r["subfamilia"].unique()) if not r.empty else set()
        es_adaptador = bool(subfams_actuales & {"ADAPTADORES I", "ADAPTADORES II"})
        if es_adaptador:
            if len(medidas) == 1:
                r = r[r["medidas_cod"].apply(lambda m: medidas[0] in m)]
            else:
                r = r[r["medidas_cod"].apply(lambda m: m == medidas)]
            medidas_aplicadas = True

    if medida and not medidas_aplicadas:
        medida_norm = medida.upper().strip().rstrip('"').strip()
        medida_cod_norm = r["medida_cod"].str.upper().str.strip().str.rstrip('"').str.strip()
        mascara = medida_cod_norm == medida_norm

        # Para medida_cod con color sufijo: "1/2" R", "1/2" N", "1/2" A" (AF AIR, etc.)
        mascara = mascara | r["medida_cod"].str.upper().str.strip().str.startswith(medida_norm + '"')

        # Buscar también por nominal equivalente (JDE/HYP usan "08", QF usa "1/2"")
        nominal_inv = {v: k for k, v in MEDIDA_NOMINAL.items()}
        nominal = nominal_inv.get(medida.strip().rstrip('"').strip())
        if nominal:
            mascara = mascara | (r["medida_cod"].str.strip() == nominal)
            # Para MatrixFlex: medida_cod es "4K-16", "6K-12", etc. → sufijo "-{nominal}"
            mascara = mascara | (r["medida_cod"].str.upper().str.endswith(f"-{nominal}"))
            # Para corrugadas: buscar también "CORG-{nominal}" (ej: CORG-10)
            if superficie == "corrugada":
                mascara = mascara | (r["medida_cod"].str.strip() == f"CORG-{nominal}")
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
    texto_lim = re.sub(r'\bx\s*\d+(?!\s*/\d)', '',texto).strip()
    texto_up  = texto_lim.upper()
    texto_lo  = normalizar_medida_texto(texto_lim.lower())

    # ── Subfamilia (categoría ERP) ────────────────────────────────────────────
    subfamilias_detectadas = None
    for alias in sorted(SUBFAMILIA_MAP, key=len, reverse=True):
        if re.search(rf'\b{re.escape(alias)}\b', texto_lo):
            subfamilias_detectadas = SUBFAMILIA_MAP[alias]
            texto_lo = re.sub(rf'\b{re.escape(alias)}\b', '', texto_lo).strip()
            break

    # ── Línea premium (exactflex, shieldflex, teknospir) ──────────────────────
    linea = None
    for alias in sorted(LINEA_ALIAS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(alias)}\b', texto_lo):
            linea = LINEA_ALIAS[alias]
            break

    # ── Superficie de cubierta (corrugada / lisa) ─────────────────────────────
    superficie = None
    for alias in sorted(SUPERFICIE_ALIAS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(alias)}\b', texto_lo):
            superficie = SUPERFICIE_ALIAS[alias]
            break

    # ── Presión (TSER Everest / MatrixFlex) ──────────────────────────────────
    presion = None
    m_psi = re.search(r'\b(\d{4})\s*(?:psi)?\b', texto_lo)
    if m_psi and m_psi.group(1) in ("4000", "5000", "6000"):
        presion = m_psi.group(1)
    if not presion:
        m_k = re.search(r'\b([456])k\b', texto_lo)
        if m_k:
            presion = m_k.group(1) + "000"  # "4k"→"4000", "5k"→"5000", "6k"→"6000"

    # ── Marca ─────────────────────────────────────────────────────────────────
    marca = None
    for alias in sorted(MARCA_ALIAS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(alias)}\b', texto_lo):
            marca = MARCA_ALIAS[alias]
            break

    # Normalizar contra aliases dinámicos del ERP (longest match primero)
    if _aliases_marcas:
        for alias_din in sorted(_aliases_marcas, key=len, reverse=True):
            if re.search(rf'\b{re.escape(alias_din)}\b', texto_lo):
                marca = _aliases_marcas[alias_din]
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

    # ── Tipo — 1) grupo ERP, 2) alias estático, 3) tipo_cod fallback ────────────
    tipo = None
    # Búsqueda dinámica contra grupos reales del ERP (longest match primero)
    grupos_bd = sorted(df["grupo"].dropna().unique().tolist(), key=len, reverse=True)
    for g in grupos_bd:
        if re.search(rf'\b{re.escape(g)}\b', texto_up):
            tipo = g
            break

    if not tipo:
        for alias in sorted(TIPO_ALIAS, key=len, reverse=True):
            if re.search(rf'\b{re.escape(alias)}\b', texto_lo):
                tipo = TIPO_ALIAS[alias]
                break

    if not tipo:
        # Fallback: búsqueda contra tipo_cod (comportamiento anterior)
        tipos_bd = sorted(df["tipo_cod"].dropna().unique().tolist(), key=len, reverse=True)
        for t in tipos_bd:
            if re.search(rf'\b{re.escape(t)}\b', texto_up):
                tipo = t
                break

    # ── Medidas múltiples (ej: 1/4 x 1/4, 1/2 x 3/4) ───────────────────────
    medidas = []
    texto_lo_norm = re.sub(r'(\d)\s*x\s*(\d)', r'\1 x \2', texto_lo)
    partes = re.split(r'\s+x\s+', texto_lo_norm)
    patron_medida = r'(\d+\s+\d+/\d+|\d+/\d+|\d+\"?)'
    medidas_candidatas = []
    for parte in partes:
        mm = re.search(patron_medida, parte.strip())
        if mm:
            medidas_candidatas.append(normalizar_medida_texto(mm.group(1).strip()))
    if len(medidas_candidatas) >= 2:
        medidas = medidas_candidatas

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

    # Entero solo (pulgadas sin símbolo): solo si hay contexto de tipo/marca/presion
    if not medida and (tipo or marca or presion):
        m = re.search(r'\b([1-6])\b', texto_lo)
        if m:
            medida = m.group(1)

    # "s" letra suelta + tipo R1/R2 = smooth (cubierta lisa), no color azul
    if color_de_letra_s and tipo in ("R1", "R2"):
        tipo = tipo + "S"
        color = None

    # "lisa"/"smooth" sin tipo específico → R1S (cubierta lisa de R1)
    # Con tipo ya definido → solo es modificador de superficie (corrugada vs lisa)
    if superficie == "lisa" and tipo is None:
        tipo = "R1S"
        superficie = None

    logger.debug(f"interpretar_linea → marca={marca} tipo={tipo} medida={medida} medidas={medidas} color={color} cant={cantidad} presion={presion} linea={linea} superficie={superficie} subfamilias={subfamilias_detectadas}")
    return marca, tipo, medida, medidas, color, cantidad, presion, linea, superficie, subfamilias_detectadas

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
    texto_sin_cant = re.sub(r'\bx\s*\d+', '',texto).strip()
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

    # ── Estrategia 0: desambiguación "código + marca" (ej: "045-08-06 DME") ──────
    # Permite al cliente elegir una variante específica de un producto multi-marca.
    tokens = texto_sin_cant.rsplit(None, 1)
    if len(tokens) == 2:
        posible_cod, posible_marca = tokens
        exactos_cod = buscar_por_codigo(posible_cod)
        if not exactos_cod.empty:
            variante = exactos_cod[exactos_cod["marca"].str.upper() == posible_marca.upper()]
            if not variante.empty:
                fila = variante.iloc[0]
                logger.info(f"Código+marca: {fila['codigo']} / {fila['marca']}")
                log_consultas.append({"timestamp": datetime.now().isoformat(), "mensaje": texto, "tipo": "codigo_marca"})
                return _ruta_imagen(str(fila.get("tipo_cod", "") or "").lower()), formatear_resultado(fila, cantidad, descuento)

    # ── Estrategia 1: código exacto ───────────────────────────────────────────
    exactos = buscar_por_codigo(texto_sin_cant)
    if not exactos.empty:
        if len(exactos) == 1:
            fila = exactos.iloc[0]
            logger.info(f"Código exacto: {fila['codigo']}")
            log_consultas.append({"timestamp": datetime.now().isoformat(), "mensaje": texto, "tipo": "codigo_exacto"})
            return _ruta_imagen(str(fila.get("tipo_cod", "") or "").lower()), formatear_resultado(fila, cantidad, descuento)
        else:
            logger.info(f"Código multi-marca: {exactos.iloc[0]['codigo']} ({len(exactos)} variantes)")
            log_consultas.append({"timestamp": datetime.now().isoformat(), "mensaje": texto, "tipo": "codigo_multi_marca"})
            return None, formatear_multi_marca(exactos)

    # ── Estrategia 2: prefijo de código ──────────────────────────────────────
    if len(texto_sin_cant) >= 3:
        prefijo = buscar_por_codigo_prefijo(texto_sin_cant)
        # Fallback VITILLO: el vendedor a veces inserta una letra extra de color
        # (VT-TH1SNN08 → VT-TH1SN08); quitar esa letra y reintentar con prefijo
        if prefijo.empty:
            m_vt = re.match(r'^(.+)([A-Z])(\d{2}(?:SL)?)$', texto_sin_cant.upper().strip())
            if m_vt:
                alt = m_vt.group(1) + m_vt.group(3)
                prefijo = buscar_por_codigo_prefijo(alt)
                if not prefijo.empty:
                    logger.info(f"Prefijo VITILLO corregido: {texto_sin_cant} → {alt}")
        if len(prefijo) == 1:
            fila = prefijo.iloc[0]
            logger.info(f"Prefijo único: {fila['codigo']}")
            log_consultas.append({"timestamp": datetime.now().isoformat(), "mensaje": texto, "tipo": "codigo_prefijo"})
            return _ruta_imagen(str(fila.get("tipo_cod", "") or "").lower()), formatear_resultado(fila, cantidad, descuento)
        elif 1 < len(prefijo) <= 15:
            return None, formatear_lista(prefijo, f"Encontré {len(prefijo)} productos con ese prefijo:")
        elif len(prefijo) > 15:
            lista = formatear_lista(prefijo.head(15), f"Mostrando 15 de {len(prefijo)} productos con ese prefijo:")
            return None, lista + "\n_Hay más resultados — escribe más caracteres para filtrar._"

    # ── Estrategia 3: tipo + medida + marca + color ───────────────────────────
    marca, tipo, medida, medidas, color, cantidad, presion, linea, superficie, subfamilias = interpretar_linea(texto)
    logger.info(f"E3 → marca={marca} tipo={tipo} medida={medida} medidas={medidas} linea={linea} presion={presion} superficie={superficie} subfamilias={subfamilias}")

    # Si tipo=="HT" vino de alias celsius/a-temp pero el usuario también dijo r1 o r2,
    # post-filtrar resultados por subtipo SAE en descripción
    sae_subtipo = None
    if tipo == "HT":
        if re.search(r'\br1\b', texto.lower()):
            sae_subtipo = r'r1at|1sn'
        elif re.search(r'\br2\b', texto.lower()):
            sae_subtipo = r'r2at|2sn'

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

        # Llamada principal con medida_busq (incluye color, EPDM y superficie)
        subtipo_ht = color if tipo == 'HT' else None
        resultados = buscar_por_tipo_medida_marca(tipo, medida_busq, marca, presion, linea, subtipo_ht, superficie, subfamilias, medidas)
        if sae_subtipo and not resultados.empty:
            resultados = resultados[resultados["descripcion"].str.contains(sae_subtipo, na=False, case=False)]

        # Si no encontró, intentar sin color/EPDM
        if resultados.empty and color and medida:
            resultados = buscar_por_tipo_medida_marca(tipo, medida, marca, presion, linea, subtipo_ht, superficie, subfamilias, medidas)
            if sae_subtipo and not resultados.empty:
                resultados = resultados[resultados["descripcion"].str.contains(sae_subtipo, na=False, case=False)]

        # Si tipo detectado pero medida no encontró resultados → mostrar opciones del tipo
        if resultados.empty and tipo and medida:
            resultados_tipo = buscar_por_tipo_medida_marca(tipo, None, marca, presion, linea, subtipo_ht, superficie, subfamilias)
            if sae_subtipo and not resultados_tipo.empty:
                resultados_tipo = resultados_tipo[resultados_tipo["descripcion"].str.contains(sae_subtipo, na=False, case=False)]
            if not resultados_tipo.empty:
                meds = sorted(resultados_tipo["medida_cod"].dropna().str.rstrip('"').str.strip().unique())
                meds_str = ", ".join(meds)
                medida_display = medida.rstrip('"').strip()
                if len(resultados_tipo) <= 12:
                    return None, (
                        f"No hay *{tipo}* en *{medida_display}\"*.\n\n"
                        + formatear_lista(resultados_tipo, "Opciones disponibles:")
                    )
                else:
                    return None, (
                        f"No hay *{tipo}* en *{medida_display}\"*.\n\n"
                        f"📐 Medidas disponibles: {meds_str}\n\n"
                        "¿Cuál necesitas?"
                    )

        if len(resultados) == 1:
            logger.info(f"Match por filtros: {resultados.iloc[0]['codigo']}")
            log_consultas.append({"timestamp": datetime.now().isoformat(), "mensaje": texto, "tipo": "filtros",
                                   "marca": marca, "tipo": tipo, "medida": medida})
            imagen = _ruta_imagen((tipo or "").lower())
            return imagen, formatear_resultado(resultados.iloc[0], cantidad, descuento)

        elif len(resultados) > 1 and resultados["codigo"].nunique() == 1:
            return None, formatear_multi_marca(resultados)

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
    hay_agotado   = False

    for i, linea in enumerate(lineas, start=1):
        # Detectar línea de descuento global
        if "descuento" in linea.lower() and not re.search(r'\bx\s*\d+', linea.lower()):
            descuento_global = extraer_descuento(linea)
            continue

        cantidad       = extraer_cantidad(linea)
        desc_linea     = extraer_descuento(linea)
        texto_sin_cant = re.sub(r'\bx\s*\d+', '',linea).strip()
        texto_sin_cant = re.sub(r'\b\d+\s*%', '', texto_sin_cant).strip()

        fila = None

        fila = None
        marca_auto = ""   # marca elegida automáticamente en caso multi-marca

        # 1. Código exacto (posiblemente multi-marca → auto-seleccionar)
        exactos = buscar_por_codigo(texto_sin_cant)
        if not exactos.empty:
            if len(exactos) == 1:
                fila = exactos.iloc[0]
            else:
                stocks = exactos.apply(_stock_total, axis=1)
                fila = exactos.loc[stocks.idxmax() if stocks.max() > 0 else exactos["precio"].idxmin()]
                marca_auto = fila["marca"]

        # 2. Código por prefijo — único código comercial (posiblemente multi-marca)
        if fila is None:
            parcial = buscar_por_codigo_prefijo(texto_sin_cant)
            if not parcial.empty and parcial["codigo"].nunique() == 1:
                if len(parcial) == 1:
                    fila = parcial.iloc[0]
                else:
                    stocks = parcial.apply(_stock_total, axis=1)
                    fila = parcial.loc[stocks.idxmax() if stocks.max() > 0 else parcial["precio"].idxmin()]
                    marca_auto = fila["marca"]

        # 3. Tipo + medida + marca
        if fila is None:
            marca, tipo, medida, medidas, color, cantidad, presion, linea_prem, sup, subfamilias = interpretar_linea(linea)
            if tipo or marca or medida:
                medida_busq = medida
                if color and medida:
                    medida_busq = f'{medida}" {color}' if not medida.endswith('"') else f'{medida} {color}'
                resultados = buscar_por_tipo_medida_marca(tipo, medida_busq, marca, presion, linea_prem, None, sup, subfamilias, medidas)
                if resultados.empty and color:
                    resultados = buscar_por_tipo_medida_marca(tipo, medida, marca, presion, linea_prem, None, sup, subfamilias, medidas)
                if len(resultados) == 1:
                    fila = resultados.iloc[0]
                elif len(resultados) > 1 and resultados["codigo"].nunique() == 1:
                    stocks = resultados.apply(_stock_total, axis=1)
                    fila = resultados.loc[stocks.idxmax() if stocks.max() > 0 else resultados["precio"].idxmin()]
                    marca_auto = fila["marca"]

        if fila is not None:
            precio      = float(fila["precio"])
            subtotal    = precio * cantidad
            pct         = desc_linea
            desc_monto  = subtotal * (pct / 100)
            subtotal_bruto   += subtotal
            total_descuentos += desc_monto
            desc_txt    = fila['descripcion'].title()[:45]
            marca_nota  = f" ({marca_auto})" if marca_auto else ""
            linea_resp  = (
                f"{i}️⃣ *{fila['codigo']}*{marca_nota} — {desc_txt}\n"
                f"   x{cantidad} × ${precio:.2f} | Subtotal: ${subtotal:.2f}"
            )
            if pct > 0:
                linea_resp += f" | Desc {pct:.0f}%: -${desc_monto:.2f}"
            if _stock_total(fila) == 0:
                linea_resp += " | ⚠️ AGOTADO†"
                hay_agotado = True
            respuesta += linea_resp + "\n\n"
        else:
            respuesta += f"{i}️⃣ ❌ _{linea}_\n\n"
            hay_error = True

    # Descuento global sobre el subtotal neto
    subtotal_neto   = subtotal_bruto - total_descuentos
    desc_global_monto = subtotal_neto * (descuento_global / 100)
    total_final     = subtotal_neto - desc_global_monto
    total_descuentos += desc_global_monto

    total_igv = total_final * (1 + IGV)

    respuesta += "─────────────────────\n"
    respuesta += f"Subtotal:       ${subtotal_bruto:.2f}\n"
    if total_descuentos > 0:
        respuesta += f"Descuentos:     -${total_descuentos:.2f}\n"
    respuesta += f"Total s/IGV:    ${total_final:.2f}\n"
    respuesta += f"🧾 *Total c/IGV: ${total_igv:.2f}*"

    if hay_agotado:
        respuesta += "\n\n_(†) Precio de referencia. Producto sin stock actualmente — consultar disponibilidad._"
    if hay_error:
        respuesta += "\n\n_(*) Algunos ítems no encontrados. Escríbeme para revisar._"

    log_consultas.append({
        "timestamp": datetime.now().isoformat(),
        "tipo": "multiple",
        "lineas": len(lineas),
        "total": total_final,
    })
    return respuesta
