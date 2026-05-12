import pandas as pd
import re
import os

log_consultas = []

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ruta_excel = os.path.join(BASE_DIR, "data", "mangueras_precios.xlsx")

try:
    df = pd.read_excel(ruta_excel)
except Exception as e:
    print("ERROR CARGANDO EXCEL:", e)
    raise e

# Normalizar columnas
df.columns = [c.strip() for c in df.columns]
df['codigo']      = df['Código'].str.strip()
df['marca']       = df['Marca'].str.strip().str.upper()
df['descripcion'] = df['Descripción'].str.strip().str.lower()
df['precio']      = df['Precio Vta.']
df['unidad']      = df['UND'].str.strip()

# Extraer tipo y medida del código para búsqueda flexible
# Estructura: PREFIJO-TIPO-MEDIDA (ej: QF-R1-1/2", JDE-4SH-12)
df['tipo_cod'] = df['codigo'].str.extract(r'^[A-Z]+-([A-Z0-9]+)-', expand=False).str.upper()
df['medida_cod'] = df['codigo'].str.extract(r'^[A-Z]+-[A-Z0-9]+-(.+)$', expand=False).str.strip()

# Mapa de alias de marca
MARCA_ALIAS = {
    'QF': 'QF', 'QINGFLEX': 'QF',
    'AF': 'AF',
    'JDE': 'JDEFLEX', 'JDEFLEX': 'JDEFLEX',
    'VT': 'VITILLO', 'VITILLO': 'VITILLO',
    'RSY': 'RUNNINGFLEX', 'RUNNINGFLEX': 'RUNNINGFLEX', 'RUNNING': 'RUNNINGFLEX',
    'SW': 'SWAGGER', 'SWAGGER': 'SWAGGER',
    'MACTUBI': 'MACTUBI',
    'HYP': 'HYP',
}

def normalizar_marca(texto):
    texto = texto.upper().strip()
    return MARCA_ALIAS.get(texto)

def formatear_resultado(fila, cantidad=1):
    subtotal = fila['precio'] * cantidad
    resp = (
        f"✅ *{fila['codigo']}*\n"
        f"📋 {fila['descripcion'].title()}\n"
        f"🏷️ Marca: {fila['marca']}\n"
        f"💰 Precio: S/ {fila['precio']:.2f} x {fila['unidad']}\n"
    )
    if cantidad > 1:
        resp += f"📦 Cantidad: {cantidad}\n"
        resp += f"💵 Subtotal: S/ {subtotal:.2f}\n"
    return resp

def buscar_por_codigo(codigo):
    """Búsqueda exacta por código"""
    resultado = df[df['codigo'].str.upper() == codigo.upper()]
    if not resultado.empty:
        return resultado.iloc[0]
    return None

def buscar_por_codigo_parcial(texto):
    """Búsqueda por código parcial o fragmento"""
    resultado = df[df['codigo'].str.upper().str.contains(texto.upper(), na=False)]
    return resultado

def buscar_por_tipo_medida_marca(tipo=None, medida=None, marca=None):
    """Búsqueda flexible por tipo, medida y/o marca"""
    resultado = df.copy()

    if tipo:
        resultado = resultado[resultado['tipo_cod'] == tipo.upper()]
    if marca:
        resultado = resultado[resultado['marca'] == marca.upper()]
    if medida:
        # búsqueda flexible en medida
        resultado = resultado[
            resultado['medida_cod'].str.upper().str.contains(
                re.escape(medida.upper()), na=False
            )
        ]
    return resultado

def buscar_por_descripcion(palabras):
    """Búsqueda por palabras clave en descripción"""
    resultado = df.copy()
    for palabra in palabras:
        resultado = resultado[
            resultado['descripcion'].str.contains(palabra.lower(), na=False)
        ]
    return resultado

def extraer_cantidad(texto):
    match = re.search(r'x\s*(\d+)', texto.lower())
    return int(match.group(1)) if match else 1

def extraer_descuento(texto):
    match = re.search(r'descuento\s*(\d+)', texto.lower())
    return float(match.group(1)) if match else 0

def interpretar_linea(texto):
    """
    Extrae marca, tipo, medida y cantidad de una línea de texto.
    Estrategia: buscar patrones conocidos del catálogo.
    """
    original = texto
    cantidad = extraer_cantidad(texto)
    texto_limpio = re.sub(r'x\s*\d+', '', texto).strip()

    # 1. Detectar marca
    marca = None
    for alias in sorted(MARCA_ALIAS.keys(), key=len, reverse=True):
        if re.search(r'\b' + alias + r'\b', texto_limpio.upper()):
            marca = MARCA_ALIAS[alias]
            break

    # 2. Detectar tipo (R1, R2, 4SH, 4SP, AIR, GL, DW, etc.)
    tipo = None
    # Alias de tipo en lenguaje natural
    TIPO_ALIAS = {
        'AIRE': 'AIR', 'AIR': 'AIR', 'AGUA': 'AIR',
        'GASOLINA': 'GL', 'GAS': 'GL',
        'VAPOR': 'STEAM', 'STEAM': 'STEAM',
    }
    for alias, t in TIPO_ALIAS.items():
        if re.search(r'\b' + alias + r'\b', texto_limpio.upper()):
            tipo = t
            break

    if not tipo:
        tipos_conocidos = df['tipo_cod'].dropna().unique().tolist()
        tipos_conocidos.sort(key=len, reverse=True)
        for t in tipos_conocidos:
            if re.search(r'\b' + re.escape(t) + r'\b', texto_limpio.upper()):
                tipo = t
                break

    # 3. Detectar medida (fracciones, pulgadas)
    medida = None
    patrones_medida = [
        r'\d+\s+\d+/\d+',   # ej: 1 1/2
        r'\d+/\d+',          # ej: 3/4
        r'\d+"',             # ej: 1"
        r'\d+\.\d+',         # ej: 1.5
    ]
    for patron in patrones_medida:
        match = re.search(patron, texto_limpio)
        if match:
            medida = match.group(0).replace('"', '').strip()
            break

    return marca, tipo, medida, cantidad

def consultar(texto: str) -> str:
    lineas = [l.strip() for l in texto.split('\n') if l.strip()]

    if len(lineas) > 1:
        return cotizar_multiple(lineas)

    texto = lineas[0]
    cantidad = extraer_cantidad(texto)

    # ── Estrategia 1: código exacto ──────────────────────
    texto_sin_cantidad = re.sub(r'x\s*\d+', '', texto).strip()
    fila = buscar_por_codigo(texto_sin_cantidad)
    if fila is not None:
        log_consultas.append({"mensaje": texto, "tipo": "codigo_exacto"})
        return formatear_resultado(fila, cantidad)

    # ── Estrategia 2: código parcial ─────────────────────
    parcial = buscar_por_codigo_parcial(texto_sin_cantidad)
    if len(parcial) == 1:
        log_consultas.append({"mensaje": texto, "tipo": "codigo_parcial"})
        return formatear_resultado(parcial.iloc[0], cantidad)
    elif len(parcial) > 1 and len(parcial) <= 10:
        return formatear_lista(parcial, f"Encontré {len(parcial)} productos similares:")

    # ── Estrategia 3: tipo + medida + marca ──────────────
    marca, tipo, medida, cantidad = interpretar_linea(texto)

    if tipo or marca or medida:
        resultados = buscar_por_tipo_medida_marca(tipo, medida, marca)

        if len(resultados) == 1:
            log_consultas.append({"mensaje": texto, "tipo": "filtros"})
            return formatear_resultado(resultados.iloc[0], cantidad)
        elif 1 < len(resultados) <= 10:
            return formatear_lista(resultados, f"Encontré {len(resultados)} opciones:")
        elif len(resultados) > 10:
            # Demasiados, pedir más datos
            detalle = []
            if not marca:
                marcas = resultados['marca'].unique()
                detalle.append(f"Marca: {', '.join(marcas)}")
            if not medida:
                medidas = resultados['medida_cod'].dropna().unique()[:8]
                detalle.append(f"Medida: {', '.join(medidas)}")
            return (
                f"Encontré {len(resultados)} productos para *{tipo or ''}*.\n\n"
                f"¿Puedes especificar más?\n" +
                '\n'.join(detalle)
            )

    # ── Estrategia 4: palabras clave en descripción ──────
    palabras = [p for p in texto_sin_cantidad.lower().split() if len(p) > 2]
    if palabras:
        resultados = buscar_por_descripcion(palabras)
        if len(resultados) == 1:
            return formatear_resultado(resultados.iloc[0], cantidad)
        elif 1 < len(resultados) <= 10:
            return formatear_lista(resultados, "Encontré estos productos:")

    # ── Sin resultados ───────────────────────────────────
    log_consultas.append({"mensaje": texto, "tipo": "sin_resultado"})
    return (
        "No encontré ese producto 😕\n\n"
        "Puedes buscar por:\n"
        "• Código exacto: `QF-R1-1/2\"`\n"
        "• Tipo y medida: `R1 1/2 QF`\n"
        "• Descripción: `aire 1/2 negro`\n\n"
        "¿Cómo lo busco? 👍"
    )

def formatear_lista(resultados, titulo):
    resp = f"{titulo}\n\n"
    for _, fila in resultados.iterrows():
        resp += f"• *{fila['codigo']}* - {fila['descripcion'].title()} → S/ {fila['precio']:.2f}\n"
    resp += "\n¿Cuál necesitas? Escribe el código exacto."
    return resp

def cotizar_multiple(lineas):
    respuesta = "Aquí tienes la cotización 👍\n\n"
    total = 0
    descuento_pct = 0

    for i, linea in enumerate(lineas, start=1):
        if 'descuento' in linea.lower():
            descuento_pct = extraer_descuento(linea)
            continue

        cantidad = extraer_cantidad(linea)
        texto_limpio = re.sub(r'x\s*\d+', '', linea).strip()

        # Buscar el producto
        fila = buscar_por_codigo(texto_limpio)

        if fila is None:
            parcial = buscar_por_codigo_parcial(texto_limpio)
            if len(parcial) == 1:
                fila = parcial.iloc[0]

        if fila is None:
            marca, tipo, medida, cantidad = interpretar_linea(linea)
            resultados = buscar_por_tipo_medida_marca(tipo, medida, marca)
            if len(resultados) == 1:
                fila = resultados.iloc[0]

        if fila is not None:
            subtotal = fila['precio'] * cantidad
            total += subtotal
            respuesta += (
                f"{i}️⃣ *{fila['codigo']}*\n"
                f"   {fila['descripcion'].title()}\n"
                f"   Cant: {cantidad} | S/ {fila['precio']:.2f} c/u | Subtotal: S/ {subtotal:.2f}\n\n"
            )
        else:
            respuesta += f"{i}️⃣ ❌ No encontrado: `{linea}`\n\n"

    descuento_monto = total * (descuento_pct / 100)
    total_final = total - descuento_monto

    respuesta += f"─────────────────\n"
    respuesta += f"Subtotal: S/ {total:.2f}\n"
    if descuento_pct > 0:
        respuesta += f"Descuento ({descuento_pct:.0f}%): -S/ {descuento_monto:.2f}\n"
    respuesta += f"*TOTAL: S/ {total_final:.2f}*"

    return respuesta
