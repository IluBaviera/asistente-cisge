"""Tests de los correctores deterministas post-OCR (funciones puras).

Cubren los bugs resueltos esta semana: B12 (género ADAP), B3 (regex de
ángulo), el redondeo de medidas y el enriquecido de subtipo de ferrula.
"""
import app.agente as agente


# ── B12 + Corrección 1: normalización de género MACHO-primero ────────────────

def test_b12_adap_genero_invertido():
    """Caso real: GPT emite ADAP con Hembra primero → debe quedar MACHO primero."""
    out = agente._corregir_adaptador_ocr([{
        "tipo": "ADAP HEMBRA JIC X MACHO JIC",
        "linea_original": "Ho. JIC 12 - M. JIC 12 = 5 und (90)",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X HEMBRA JIC"
    assert out["angulo"] == "90"


def test_b12_espiga_mal_clasificada_a_adap():
    out = agente._corregir_adaptador_ocr([{
        "tipo": "ESPIGA HEMBRA JIC",
        "linea_original": "H. JIC 16 - M. JIC 16 (90)",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X HEMBRA JIC"
    assert out["angulo"] == "90"


def test_b12_macho_macho_conserva_orden():
    out = agente._corregir_adaptador_ocr([{
        "tipo": "ADAP MACHO JIC X MACHO NPT",
        "linea_original": "M. JIC -06 - M. NPT 06",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X MACHO NPT"


def test_b12_idempotente_sobre_tipo_correcto():
    out = agente._corregir_adaptador_ocr([{
        "tipo": "ADAP MACHO JIC X HEMBRA JIC",
        "linea_original": "M. JIC 12 - H. JIC 12",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X HEMBRA JIC"


def test_b12_sin_dos_pares_no_toca_tipo():
    out = agente._corregir_adaptador_ocr([{
        "tipo": "ADAP MACHO JIC X HEMBRA JIC",
        "linea_original": "adaptador surtido",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X HEMBRA JIC"


# ── Niple = adaptador macho-macho de dos roscas sin género ───────────────────

def test_niple_recto_bsp_jic():
    """'Niple recto BSP 4 - JIC 6' → ADAP MACHO JIC X MACHO BSP, medidas 3/8 x 1/4.
    JIC va primero (orden del catálogo); códigos dash a pulgada."""
    out = agente._corregir_adaptador_ocr([{
        "tipo": "", "linea_original": "Niple recto BSP 4 - JIC 6",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X MACHO BSP"
    assert out["medidas"] == ["3/8", "1/4"]


def test_niple_90_boss_jic():
    out = agente._corregir_adaptador_ocr([{
        "tipo": "", "linea_original": "Niple 90° BOSS 16 - JIC 16",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X MACHO BOSS"
    assert out["medidas"] == ["1", "1"]
    assert out["angulo"] == "90"


def test_niple_jic_primero_conserva_orden():
    """Si el vendedor ya pone JIC primero, no se invierte."""
    out = agente._corregir_adaptador_ocr([{
        "tipo": "", "linea_original": "Niple recto JIC 8 - NPT 4",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X MACHO NPT"
    assert out["medidas"] == ["1/2", "1/4"]


def test_adap_sin_genero_default_macho():
    """Regla: adaptador sin macho/hembra declarado → MACHO ambos lados."""
    out = agente._corregir_adaptador_ocr([{
        "tipo": "ADAP JIC X BSP", "linea_original": "adaptador jic 6 x bsp 4",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X MACHO BSP"


# ── B3: regex de ángulo anclado ──────────────────────────────────────────────

def test_b3_angulo_entre_parentesis():
    out = agente._corregir_adaptador_ocr([{
        "tipo": "ADAP MACHO JIC X HEMBRA JIC",
        "linea_original": "M. JIC 12 - H. JIC 12 = 5 und (45°)",
    }])[0]
    assert out["angulo"] == "45"


def test_b3_cantidad_90_no_es_angulo():
    """'= 90 und' es cantidad, no ángulo."""
    out = agente._corregir_adaptador_ocr([{
        "tipo": "ADAP MACHO NPT X MACHO NPT",
        "linea_original": "M. NPT 08 - M. NPT 08 = 90 und",
    }])[0]
    assert not out.get("angulo")


def test_b3_codigo_090_no_es_angulo():
    out = agente._corregir_adaptador_ocr([{
        "tipo": "ADAP MACHO JIC X HEMBRA JIC",
        "linea_original": "090-06-06 adaptador",
    }])[0]
    assert not out.get("angulo")


# ── _corregir_medidas_ocr: GPT redondea 3/16 → 1/4 ───────────────────────────

def test_corregir_medidas_restaura_3_16():
    out = agente._corregir_medidas_ocr([{
        "linea_original": "terminal jic h 3/16 x 3/16 90°",
        "medidas": ["1/4", "1/4"],
        "medida": "",
    }])[0]
    assert out["medidas"] == ["3/16", "3/16"]


# ── _enriquecer_tipo_ferrula: inyecta subtipo SAE ────────────────────────────

def test_enriquecer_ferrula_inyecta_subtipo():
    out = agente._enriquecer_tipo_ferrula([{
        "tipo": "FERRULA",
        "linea_original": "ferrula r12 1/2",
    }])[0]
    assert out["tipo"] == "FERRULA R12"
