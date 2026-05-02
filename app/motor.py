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
        return (
                f"Manguera hidráulica {tipo.upper()} {medida} {marca.capitalize()}\n"
                f"💰 Precio: ${fila['precio']:.2f}\n"
                f"📦 Código: {fila['codigo']}\n\n"
                f"¿Necesitas otra medida o tipo?"
                )   
    else:
        return "No encontré ese producto. ¿Puedes verificar los datos?"

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


def consultar(texto: str) -> str:
    marca, tipo, medida = interpretar_mensaje(texto)

    if not marca or not tipo or not medida:

        return (
            "Te ayudo 👍\n\n"
            "Solo necesito un poco más de info:\n"
            "• Tipo (R1, R2, R6)\n"
            "• Medida (1/4, 3/8, 1/2...)\n"
            "• Marca (Qingflex o Vitillo)\n\n"
            "Ejemplo: 'R1 1/4 Qingflex'"
        )

    return buscar_producto(marca, tipo, medida)
