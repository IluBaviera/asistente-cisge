"""Tests de los correctores deterministas post-OCR (funciones puras).

Cubren los bugs resueltos esta semana: B12 (género ADAP), B3 (regex de
ángulo), el redondeo de medidas y el enriquecido de subtipo de ferrula.
"""
import pandas as pd
import app.agente as agente


# ── Preferencia de línea de código B06 > B01 (adaptadores JIC×BSP) ────────────

def _fila_b0(cod, stock):
    return {"codigo": cod, "marca": "DME", "subfamilia": "ADAPTADORES I",
            "almacenes": {"A": stock}, "descripcion": "adap", "precio": 1.0, "unidad": "PZA"}


def test_b06_preferido_con_stock():
    df = pd.DataFrame([_fila_b0("B06-08-06", 100), _fila_b0("B01-08-06", 50)])
    assert agente._elegir_fila_por_prioridad(df, 1)["codigo"] == "B06-08-06"


def test_b06_sin_stock_cae_a_b01():
    df = pd.DataFrame([_fila_b0("B06-08-06", 0), _fila_b0("B01-08-06", 50)])
    assert agente._elegir_fila_por_prioridad(df, 1)["codigo"] == "B01-08-06"


def test_b06_b01_ambos_sin_stock_gana_b06():
    df = pd.DataFrame([_fila_b0("B06-08-06", 0), _fila_b0("B01-08-06", 0)])
    assert agente._elegir_fila_por_prioridad(df, 1)["codigo"] == "B06-08-06"


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


def test_adap_genero_abreviado_pegado():
    """'mbsp 16 m jic 16' (género 'm' pegado/suelto, códigos dash) → ADAP MACHO
    JIC X MACHO BSP, medidas 1 x 1 (JIC primero)."""
    out = agente._corregir_adaptador_ocr([{
        "tipo": "ADAP", "linea_original": "Adao mbsp 16 m jic 16 =20",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X MACHO BSP"
    assert out["medidas"] == ["1", "1"]


def test_adap_abreviado_sin_tipo_gpt():
    """'Bsp 08 mjic 12' sin tipo del GPT → ADAP MACHO JIC X MACHO BSP 3/4 x 1/2."""
    out = agente._corregir_adaptador_ocr([{
        "tipo": "", "linea_original": "Bsp 08 mjic 12 =30",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X MACHO BSP"
    assert out["medidas"] == ["3/4", "1/2"]


def test_adap_genero_abreviado_hembra():
    """'h npt 8 m jic 6' → respeta géneros: HEMBRA NPT, MACHO JIC (JIC primero)."""
    out = agente._corregir_adaptador_ocr([{
        "tipo": "", "linea_original": "adap h npt 8 m jic 6",
    }])[0]
    assert out["tipo"] == "ADAP MACHO JIC X HEMBRA NPT"


def test_bushing_no_se_reinterpreta_como_adap():
    """Un bushing (dos roscas) NO debe hijackearse a ADAP."""
    out = agente._corregir_adaptador_ocr([{
        "tipo": "BUSHING MACHO JIC X HEMBRA JIC",
        "linea_original": "bushing m jic 20 h jic 16",
    }])[0]
    assert out["tipo"] == "BUSHING MACHO JIC X HEMBRA JIC"


# ── Union M métrico × M NPT (DIN 2353): serie del par (M, tubo) ──────────────

def test_union_mnpt_serie_L():
    """'M14 tubo 8 x 1/4 npt' → UNION M METRICO X M NPT, tubo 08L, npt 1/4."""
    out = agente._corregir_union_metrico_npt([{
        "linea_original": "Adap m14 tubo 8 x 1/4 npt =40",
    }])[0]
    assert out["tipo"] == "UNION M METRICO X M NPT"
    assert out["tubo"] == "08L"
    assert out["medida"] == "1/4"


def test_union_mnpt_serie_S_desambigua_tubo6():
    """Mismo tubo 6 pero M distinto → serie distinta: M12→06L, M14→06S."""
    l12 = agente._corregir_union_metrico_npt([{"linea_original": "M12 tubo 6 x 1/4 npt"}])[0]
    l14 = agente._corregir_union_metrico_npt([{"linea_original": "M14 tubo 6 x 1/4 npt"}])[0]
    assert l12["tubo"] == "06L"
    assert l14["tubo"] == "06S"


def test_union_mnpt_90_es_adap():
    out = agente._corregir_union_metrico_npt([{
        "linea_original": "Adap a 90 m16 tubo 8 x 1/4 npt",
    }])[0]
    assert out["tipo"] == "ADAP 90° MACHO METRICO X MACHO NPT"


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


# ── _corregir_ferrula_4sh: 4SH/4SP → 00400 (no-T/M), R12 → M90010 (T/M) ───────

def test_ferrula_4sh_fuerza_no_tm():
    """4SH es la 00400 (no-T/M bajo R12) → ferrula_tm='no'."""
    out = agente._corregir_ferrula_4sh([{
        "tipo": "FERRULA R12", "linea_original": 'FERRULA 2" 4SH', "ferrula_tm": "si",
    }])[0]
    assert out["tipo"] == "FERRULA R12"
    assert out["ferrula_tm"] == "no"


def test_ferrula_4sp_detecta():
    out = agente._corregir_ferrula_4sh([{
        "tipo": "FERRULA", "linea_original": "ferrula 4sp 3/4", "ferrula_tm": "si",
    }])[0]
    assert out["ferrula_tm"] == "no"


def test_ferrula_r12_conserva_tm_por_defecto():
    """R12 a secas NO es 4SH → conserva su T/M (M90010)."""
    out = agente._corregir_ferrula_4sh([{
        "tipo": "FERRULA R12", "linea_original": "ferrula r12 1", "ferrula_tm": "si",
    }])[0]
    assert out["ferrula_tm"] == "si"


def test_manguera_4sh_no_se_toca():
    """'4SH' en una manguera (no ferrula) no debe tocarse."""
    out = agente._corregir_ferrula_4sh([{
        "tipo": "4SH", "linea_original": "manguera 4sh 1 vitillo", "ferrula_tm": "",
    }])[0]
    assert out["tipo"] == "4SH"
    assert out.get("ferrula_tm") == ""


# ── Continuación conversacional: marca suelta tras mostrar un producto ───────

def test_continuacion_marca_cotiza_ultimo_producto(monkeypatch):
    """Tras ver el producto multi-marca 045-08-06, responder 'DME' cotiza ese
    código con esa marca (sin caer en los filtros)."""
    import app.motor as motor
    r = motor.buscar_por_codigo("045-08-06")
    ult = motor.formatear_multi_marca(r)
    monkeypatch.setattr(agente, "cargar_historial",
                        lambda n: [{"role": "assistant", "content": ult}])
    out = agente._resolver_continuacion_marca("DME", "111", 1, 0)
    assert out is not None
    assert "045-08-06" in out and "DME" in out


def test_continuacion_ignora_palabra_no_marca(monkeypatch):
    """'hola' no es marca → no dispara continuación (cae al flujo normal)."""
    monkeypatch.setattr(agente, "cargar_historial",
                        lambda n: [{"role": "assistant", "content": "📋 *045-08-06*"}])
    assert agente._resolver_continuacion_marca("hola", "111", 1, 0) is None


def test_continuacion_sin_producto_previo(monkeypatch):
    """Marca válida pero sin producto reciente en el historial → None."""
    monkeypatch.setattr(agente, "cargar_historial", lambda n: [])
    assert agente._resolver_continuacion_marca("DME", "111", 1, 0) is None


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
