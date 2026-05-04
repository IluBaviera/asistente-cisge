log_consultas = []
import pandas as pd
import re

# Cargar datos
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ruta_excel = os.path.join(BASE_DIR, "data", "precios.xlsx")

try:
    df = pd.read_excel(ruta_excel)
except Exception as e:
    print("ERROR CARGANDO EXCEL:", e)
    raise e

# Normalizar columnas
df.columns = ['codigo', 'tipo', 'medida', 'marca', 'precio']

df['tipo'] = df['tipo'].str.lower().str.strip()
df['marca'] = df['marca'].str.lower().str.strip()
df['medida'] = df['medida'].str.replace('"', '').str.strip().str.lower()

# Estandarizar marca
df['marca'] = df['marca'].replace({
    'qf': 'qingflex'
})

def buscar_producto(marca, tipo, medida):
    resultado = df[
        (df['marca'] == marca) &
        (df['tipo'] == tipo) &
        (df['medida'] == medida)
    ]

    if not resultado.empty:
        fila = resultado.iloc[0]

        respuesta = (
            f"Claro 👍\n\n"
            f"Manguera hidráulica {tipo.upper()} {medida} {marca.capitalize()}\n"
            f"💰 Precio: ${fila['precio']:.2f}\n"
            f"📦 Código: {fila['codigo']}\n"
        )

        # 🔥 SUGERENCIA (upselling)
        if tipo == "r1":
            respuesta += (
            "\n💡 Recomendación:\n"
            "Si el equipo tiene mayor exigencia o uso continuo, "
            "te conviene una versión reforzada de R1 para mayor durabilidad.\n"
            )   

        return respuesta
    else:
        return (
            "No encontré ese producto 😕\n\n"
            "Puede ser por:\n"
            "• Marca\n"
            "• Medida\n"
            "• Tipo\n\n"
            "Si quieres, dime nuevamente y lo revisamos 👍"
        )

def interpretar_mensaje(texto):
    texto = texto.lower()

    # tipo
    tipo = None
    if "r1" in texto:
        tipo = "r1"
    elif "r2" in texto:
        tipo = "r2"
    elif "r6" in texto:
        tipo = "r6"

    # medida
    medida = None
    if re.search(r"\b1/4\b", texto) or "un cuarto" in texto:
        medida = "1/4"
    elif re.search(r"\b3/8\b", texto):
        medida = "3/8"
    elif re.search(r"\b1/2\b", texto) or "media" in texto:
        medida = "1/2"
    elif re.search(r"\b5/8\b", texto):
        medida = "5/8"
    elif re.search(r"\b3/4\b", texto):
        medida = "3/4"

    # marca
    marca = None
    if "vitillo" in texto:
        marca = "vitillo"
    elif "qf" in texto or "qingflex" in texto:
        marca = "qingflex"

    return marca, tipo, medida



def obtener_medidas_disponibles(tipo):
    medidas = df[df['tipo'] == tipo]['medida'].unique()
    return sorted(medidas)

def consultar(texto: str) -> str:
    marca, tipo, medida = interpretar_mensaje(texto)

    # 1. Validar tipo
    if not tipo:
        respuesta = (
            "Te ayudo 👍\n\n"
            "Indícame el tipo:\n"
            "• R1\n• R2\n• R6"
        )

    # 2. Validar medida
    elif not medida:
        medidas = obtener_medidas_disponibles(tipo)

        lista = "\n".join([f"• {m}" for m in medidas])

        respuesta = (
            f"Te ayudo 👍\n\n"
            f"Estas son las medidas disponibles en {tipo.upper()}:\n"
            f"{lista}\n\n"
            "¿Cuál necesitas?"
        )

    # 3. Buscar producto
    else:
        if not marca:
            respuesta = (
                "No indicaste marca 👀\n"
                "Te cotizo Qingflex por defecto:\n\n"
                + buscar_producto("qingflex", tipo, medida)
            )
        else:
            respuesta = buscar_producto(marca, tipo, medida)

    # 🔥 LOG
    log_consultas.append({
        "mensaje": texto,
        "marca": marca,
        "tipo": tipo,
        "medida": medida,
        "respuesta": respuesta
    })

    return respuesta

