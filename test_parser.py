"""
Test del parser GPT-4.1 Mini para consultas comerciales CISGE.
Independiente de app/ — solo usa openai + dotenv.
"""
import json
import time
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """\
Eres un parser de consultas comerciales para CISGE, distribuidora peruana.
Extrae del texto: tipo de manguera (R1/R2/4SH/4SP/AIR/etc), medida (fracción en pulgadas), marca (QF/JDEFLEX/VITILLO/MACTUBI/AF).
Evalúa tu confianza en la extracción: high/medium/low.
Devuelve SOLO JSON válido, sin texto adicional:
{"tipo":"","medida":"","marca":"","confidence":"high|medium|low","pregunta":"(solo si confidence es low, la pregunta específica a hacerle al usuario)"}
Si confidence es low, deja tipo/medida/marca vacíos y agrega el campo pregunta.
La medida siempre en formato numérico o fracción: 1/2, 3/4, 1, 1 1/4. Nunca escribas 'pulgada', 'media' ni texto adicional."""

CONSULTAS = [
    "R2 3/4 JDE",
    "QF-R1-1/2",
    "manguera r1 media pulgada qf",
    "4SH 1 pulgada vitillo",
    "r2 3/4 con descuento 10%",
    "manguera hidraulica 3/4",
    "r2 jdeflex",
    "manguera de 1 pulgada",
    "espiga jic 3/4",
    "ferrula r2 media",
    "manguera para excavadora cat",
    "algo para alta presion",
    "manguera roja",
    "necesito manguera resistente",
    "que mangueras tienen?",
    "buenos días",
    "cuanto cuesta la manguera?",
    "tienen stock?",
    "hola necesito ayuda",
    "precio de la r2",
]


def parsear(consulta: str) -> tuple[dict, float]:
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": consulta},
        ],
        temperature=0,
    )
    ms = (time.perf_counter() - t0) * 1000
    texto = resp.choices[0].message.content.strip()
    try:
        data = json.loads(texto)
    except json.JSONDecodeError:
        data = {"error": "JSON invalido", "raw": texto}
    return data, ms


def main():
    COL_Q  = 35
    COL_J  = 70
    COL_MS = 8

    header = f"{'#':>2}  {'Consulta':<{COL_Q}}  {'JSON':<{COL_J}}  {'ms':>{COL_MS}}"
    print(header)
    print("-" * len(header))

    tiempos = []
    for i, consulta in enumerate(CONSULTAS, start=1):
        data, ms = parsear(consulta)
        tiempos.append(ms)

        consulta_display = consulta if len(consulta) <= COL_Q else consulta[:COL_Q - 1] + "…"
        json_str = json.dumps(data, ensure_ascii=False)
        json_display = json_str if len(json_str) <= COL_J else json_str[:COL_J - 1] + "…"

        print(f"{i:>2}  {consulta_display:<{COL_Q}}  {json_display:<{COL_J}}  {ms:>{COL_MS}.0f}")

    print("-" * len(header))
    print(f"Promedio: {sum(tiempos)/len(tiempos):.0f} ms  |  "
          f"Min: {min(tiempos):.0f} ms  |  Max: {max(tiempos):.0f} ms")


if __name__ == "__main__":
    main()
