"""Tests del corazón del motor: buscar_por_tipo_medida_marca.

Usa el df sintético inyectado por conftest (autouse). Los casos C1 y C2
están marcados xfail: documentan los bugs vivos hoy y virarán a xpass
cuando se corrijan, sin romper la suite mientras tanto.
"""
import pytest
import app.motor as motor


def _cods(df):
    return sorted(df["codigo"].tolist())


# ── Matching de tipo ─────────────────────────────────────────────────────────

def test_tipo_recto_excluye_90():
    """ESPIGA HEMBRA JIC sin ángulo → solo el grupo recto, no el 90°."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA JIC")
    assert _cods(r) == ["24791-12-12"]
    assert not r["grupo"].str.contains("90").any()


def test_angulo_inyectado_filtra_90():
    """ESPIGA HEMBRA JIC + ángulo 90 → solo el grupo 90°."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA JIC", angulo="90")
    assert _cods(r) == ["26791-04-03", "26791-04-04", "26791-12-12"]
    assert r["grupo"].str.contains("90").all()


def test_tubo_metrica_filtra_por_med_tubo():
    """Búsqueda por tubo (TUB 15): solo métricas con med_tubo='15'."""
    r = motor.buscar_por_tipo_medida_marca(tubo="15")
    assert set(r["codigo"]) == {"20491T-22-08", "20491T-22-06"}


def test_tubo_mas_manguera_afina():
    """TUB 15 + manguera 1/2 → el de hose 1/2."""
    r = motor.buscar_por_tipo_medida_marca(tubo="15", medidas=["1/2"])
    assert r["codigo"].tolist() == ["20491T-22-08"]


def test_tubo_acepta_sufijo_mm():
    """'15mm' se normaliza a '15'."""
    r = motor.buscar_por_tipo_medida_marca(tubo="15mm")
    assert not r.empty
    assert (r["med_tubo"] == "15").all()


def test_tubo_inexistente_vacio():
    r = motor.buscar_por_tipo_medida_marca(tubo="99")
    assert r.empty


def test_tubo_no_afecta_productos_sin_med_tubo():
    """Un producto sin med_tubo (espiga JIC) nunca sale en una búsqueda por tubo."""
    r = motor.buscar_por_tipo_medida_marca(tubo="15")
    assert "26791-12-12" not in r["codigo"].tolist()


def test_bushing_reductor_dos_medidas():
    """Caso 'bushing 20 mj -16 fj': BUSHING M JIC 1 1/4 x H JIC 1 → 2215-20-16.
    El código 2215-20-16 da medidas_cod limpio ['1 1/4','1'] (sin espurios)."""
    r = motor.buscar_por_tipo_medida_marca(
        tipo="BUSHING MACHO JIC X HEMBRA JIC", medidas=["1 1/4", "1"])
    assert r["codigo"].tolist() == ["2215-20-16"]


def test_bsp_equivale_a_bspp():
    """tipo con BSP debe matchear el grupo nombrado con BSPP."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ADAP MACHO JIC X MACHO BSP")
    assert _cods(r) == ["050-08-08"]


# ── Filtro de marca ──────────────────────────────────────────────────────────

def test_marca_existente_filtra_multimarca():
    r = motor.buscar_por_tipo_medida_marca(tipo="ADAP MACHO JIC X HEMBRA NPT", marca="DME")
    assert _cods(r) == ["045-08-06"]
    assert (r["marca"] == "DME").all()


def test_marca_inexistente_devuelve_vacio():
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA JIC", marca="NOEXISTE")
    assert r.empty


# ── sanitizar_marca: prefijo de código del vendedor no es marca ──────────────

def test_sanitizar_marca_prefijo_codigo_se_descarta():
    """'HP' del código 'HP-22070004' no es marca (aunque HP sea marca real)."""
    assert motor.sanitizar_marca("HP", '1 HP-22070004 S/M FERRULA R7 1/4" 50 UND') == ""


def test_sanitizar_marca_sm_fuerza_sin_marca():
    """'S/M' (Sin Marca) explícito → marca vacía."""
    assert motor.sanitizar_marca("LT", "10 ZZ-1 S/M UNION ESPIGA 1/2") == ""


def test_sanitizar_marca_real_suelta_se_conserva():
    """Una marca mencionada como token propio se conserva."""
    assert motor.sanitizar_marca("LT", "ferrula r7 1/4 LT") == "LT"


def test_sanitizar_marca_pegada_y_suelta_se_conserva():
    """Si aparece pegada a un código PERO también suelta, es marca real."""
    assert motor.sanitizar_marca("HP", "HP-22070004 ferrula r7 marca HP") == "HP"


def test_sanitizar_marca_vacia_no_crashea():
    assert motor.sanitizar_marca("", "cualquier texto") == ""


# ── Sinónimo de tipo: 'union espiga' del vendedor = 'union escamada' catálogo ──

def _payload_escamada():
    def _p(cod, grupo, med):
        return {"codigo": cod, "descripcion": f'union escamada {med}"',
                "marca": "LT", "precio": 1.3, "unidad": "PZA", "almacenes": {},
                "subfamilia": "ESPIGAS I", "grupo": grupo}
    return {"productos": [
        _p("90011-08", "UNION ESCAMADA R2", "1/2"),
        _p("90012-08", "UNION ESCAMADA R12", "1/2"),        # solapa con R2
        _p("90012-20", "UNION ESCAMADA R12", "1 1/4"),      # exclusiva de R12
    ]}


def test_union_espiga_resuelve_a_escamada(monkeypatch):
    """'UNION ESPIGA [HIDRAULICO]' (término del vendedor) debe canonizarse a
    'UNION ESCAMADA' y encontrar el producto, descartando ruido como HIDRAULICO."""
    monkeypatch.setattr(motor, "df", motor._build_df_from_api(_payload_escamada()))
    for t in ("UNION ESPIGA", "UNION ESPIGA HIDRAULICO", "union espiga hidraulico mang"):
        r = motor.buscar_por_tipo_medida_marca(tipo=t, medida="1/2")
        assert r["codigo"].tolist() == ["90011-08"], t   # R2 prioritario


def test_union_espiga_r2_fallback_a_r12(monkeypatch):
    """Preferencia R2 es SUAVE: una medida que solo existe en R12 cae a R12."""
    monkeypatch.setattr(motor, "df", motor._build_df_from_api(_payload_escamada()))
    r = motor.buscar_por_tipo_medida_marca(tipo="UNION ESPIGA", medida="1 1/4")
    assert r["codigo"].tolist() == ["90012-20"]


# ── Filtro de medidas (estricto) ─────────────────────────────────────────────

def test_medidas_reductor_inexistente_vacio():
    """Dos medidas explícitas sin match exacto → vacío (no fallthrough)."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA JIC", medidas=["1/4", "1/2"])
    assert r.empty


# ── Regresión B1: buscar sin tipo no debe lanzar NameError ───────────────────

def test_b1_busqueda_sin_tipo_no_crashea():
    """Antes de B1, tipo=None lanzaba NameError (tipo_up sin definir)."""
    r = motor.buscar_por_tipo_medida_marca(marca="DME")  # no debe lanzar
    import pandas as pd
    assert isinstance(r, pd.DataFrame)


def test_b13_marca_sola_no_colapsa_a_ferrula():
    """B13: buscar solo por marca NO debe colapsar a férrulas T/M.
    Antes devolvía vacío (el filtro ferrula_tm se aplicaba siempre)."""
    r = motor.buscar_por_tipo_medida_marca(marca="DME")
    assert not r.empty
    assert (r["marca"] == "DME").all()
    # devuelve los productos DME, no solo (o ninguna) férrula T/M
    assert set(r["codigo"]) == {"045-08-06", "050-08-08", "099-16-16"}


def test_ferrula_r12_tm_distingue_4sh_de_r12(monkeypatch):
    """La 4SH es 00400 (grupo 'FERRULA R12', no-T/M) y la R12 real es M90010
    (grupo 'FERRULA R12 T/M'). El flag ferrula_tm los separa: 'no'→00400, 'si'→M90010."""
    payload = {"productos": [
        {"codigo": "00400-16", "descripcion": 'ferrula 4sp / 4sh  1"', "marca": "LT",
         "precio": 1.0, "unidad": "PZA", "almacenes": {}, "subfamilia": "FERRULAS",
         "grupo": "FERRULA R12"},
        {"codigo": "M90010-16", "descripcion": 'ferrula r12  1"', "marca": "LT",
         "precio": 1.0, "unidad": "PZA", "almacenes": {}, "subfamilia": "FERRULAS",
         "grupo": "FERRULA R12 T/M"},
    ]}
    monkeypatch.setattr(motor, "df", motor._build_df_from_api(payload))
    r_no = motor.buscar_por_tipo_medida_marca(tipo="FERRULA R12", medida="1", ferrula_tm="no")
    assert r_no["codigo"].tolist() == ["00400-16"]      # 4SH
    r_si = motor.buscar_por_tipo_medida_marca(tipo="FERRULA R12", medida="1", ferrula_tm="si")
    assert r_si["codigo"].tolist() == ["M90010-16"]     # R12 real


def test_b13_ferrula_sigue_aplicando_tm_por_defecto():
    """Contraprueba B13: una búsqueda de férrula sí aplica T/M por defecto."""
    r = motor.buscar_por_tipo_medida_marca(tipo="FERRULA R2", medida="1/2")
    assert r["codigo"].tolist() == ["03310-08"]  # la T/M, no la lisa 00210-08


# ── C1 y C2: bugs confirmados, pendientes de fix (xfail) ──────────────────────

def test_ferrula_por_medida_encuentra_tm():
    """REGRESIÓN (rotura por C1): el código de férrula 03310-08 extrae un '10'
    espurio de su cuerpo → medidas_cod=['5/8','1/2']. NO debe tratarse como
    reductor: buscar FERRULA R2 1/2 debe devolver la variante T/M."""
    r = motor.buscar_por_tipo_medida_marca(tipo="FERRULA R2", medida="1/2")
    assert r["codigo"].tolist() == ["03310-08"]


def test_c1_par_uniforme_excluye_reductor_poblado():
    """C1 resuelto vía campos: '3/16 x 3/16' (par_uniforme) sobre familia poblada
    NO debe devolver el reductor 1/4 x 3/16 (med_rosca_1=1/4 != 3/16)."""
    r = motor.buscar_por_tipo_medida_marca(
        tipo="ESPIGA HEMBRA JIC", medida="3/16", angulo="90", par_uniforme=True)
    assert r.empty


def test_c1_par_uniforme_conserva_uniforme():
    """Contraprueba: '3/4 x 3/4' (par_uniforme) sí devuelve el uniforme 12-12."""
    r = motor.buscar_por_tipo_medida_marca(
        tipo="ESPIGA HEMBRA JIC", medida="3/4", angulo="90", par_uniforme=True)
    assert r["codigo"].tolist() == ["26791-12-12"]


def test_par_uniforme_no_toca_productos_sin_campos():
    """Seguridad: par_uniforme NO afecta productos sin campos poblados
    (férrula sin med_*): sigue devolviendo su resultado normal."""
    r = motor.buscar_por_tipo_medida_marca(
        tipo="FERRULA R2", medida="1/2", par_uniforme=True)
    assert r["codigo"].tolist() == ["03310-08"]


def test_medida_simple_sin_par_uniforme_no_excluye():
    """Una medida simple (no 'X x X') no activa la exclusión: '3/16' a secas
    sigue matcheando el reductor por lado manguera (comportamiento permisivo)."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA JIC", medida="3/16", angulo="90")
    assert "26791-04-03" in r["codigo"].tolist()


def test_c2_rosca_metrica_inexistente_no_fallthrough():
    """C2 (resuelto): pedir M12 (no existe, mínimo M14) no debe caer a M14/M24."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA MM PESADA", medida="M12", angulo="90")
    assert r.empty


def test_c2_rosca_metrica_existente_si_matchea():
    """Contraprueba C2: M24 sí existe y debe encontrarse."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA MM PESADA", medida="M24", angulo="90")
    assert sorted(r["codigo"].tolist()) == ["20591T-24-08"]


def test_c2_tolera_pitch_pegado(monkeypatch):
    """C2 boundary: 'm18x1.5' (pitch pegado) debe matchear M18. Con el \\b
    final viejo no matcheaba (no hay frontera entre '8' y 'x')."""
    payload = {"productos": [{
        "codigo": "20591T-18-04",
        "descripcion": 'espiga 90° hembra metrica pesada r2 / r12 m18x1.5 x 1/4"',
        "marca": "LT", "precio": 5.0, "unidad": "UND", "almacenes": {},
        "subfamilia": "ESPIGAS I", "grupo": "ESPIGA 90° HEMBRA MM PESADA R2",
    }]}
    monkeypatch.setattr(motor, "df", motor._build_df_from_api(payload))
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA MM PESADA", medida="M18", angulo="90")
    assert r["codigo"].tolist() == ["20591T-18-04"]
