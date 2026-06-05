"""
Test del pipeline de imagen: OCR simulado -> _parsear_lineas_imagen -> _buscar_con_parsed
"""
import sys, asyncio
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()

from app.agente import _parsear_lineas_imagen, _buscar_con_parsed

# Texto OCR simulado — incluye patrones terminal/espiga y adaptador
TEXTO_OCR = """\
ESPIGA MACHO NPT 1/2 x 100
ESPIGA HEMBRA ORFS 3/4 x 50
terminal JIC 16 - 12 Esp x 30
NPT08 - JIC16 90 x 20
JIC16-JIC12 x 15
BSP12-ORFS08 x 10
FERRULA 1/4 x 80
"""

async def main():
    print("=" * 60)
    print("TEST: pipeline imagen OCR -> parser -> motor")
    print("=" * 60)
    print(f"\nTexto OCR de entrada:\n{TEXTO_OCR}")

    print("Paso 1 -- llamando _parsear_lineas_imagen ...")
    try:
        parsed_list = await _parsear_lineas_imagen(TEXTO_OCR)
    except Exception as e:
        print(f"ERROR en _parsear_lineas_imagen: {e}")
        return

    print(f"\n{len(parsed_list)} items parseados:")
    for i, item in enumerate(parsed_list, 1):
        tipo      = item.get("tipo", "?")
        medida    = item.get("medida", "")
        medidas   = item.get("medidas", [])
        angulo    = item.get("angulo", "")
        cola      = item.get("cola", "")
        cantidad  = item.get("cantidad", 1)
        subfam    = item.get("subfamilias", [])
        print(f"  {i}. tipo={tipo!r:<40} medida={medida!r} medidas={medidas} "
              f"angulo={angulo!r} cola={cola!r} cant={cantidad} subfam={subfam}")

    all_dicts = all(isinstance(item, dict) for item in parsed_list)
    print(f"\n Todos son dicts? {'SI' if all_dicts else 'NO -- ' + str([type(i).__name__ for i in parsed_list])}")

    print("\n" + "=" * 60)
    print("Paso 2 -- _buscar_con_parsed para cada item:")
    print("=" * 60)
    for i, parsed in enumerate(parsed_list, 1):
        linea    = parsed.get("linea_original", "?")
        cantidad = parsed.get("cantidad", 1)
        resultado = _buscar_con_parsed(parsed)
        if resultado:
            preview = resultado[:180].replace("\n", " | ").encode("ascii", "replace").decode()
            print(f"  {i}. OK '{linea}' (x{cantidad}) -> {preview}...")
        else:
            print(f"  {i}. SIN RESULTADO '{linea}'")

asyncio.run(main())
