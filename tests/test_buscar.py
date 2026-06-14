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


# ── C1 y C2: bugs confirmados, pendientes de fix (xfail) ──────────────────────

def test_ferrula_por_medida_encuentra_tm():
    """REGRESIÓN (rotura por C1): el código de férrula 03310-08 extrae un '10'
    espurio de su cuerpo → medidas_cod=['5/8','1/2']. NO debe tratarse como
    reductor: buscar FERRULA R2 1/2 debe devolver la variante T/M."""
    r = motor.buscar_por_tipo_medida_marca(tipo="FERRULA R2", medida="1/2")
    assert r["codigo"].tolist() == ["03310-08"]


@pytest.mark.xfail(reason="C1: exclusión de reductores revertida (medidas_cod no fiable); "
                          "requiere extracción de medidas por cola de guiones",
                   strict=False)
def test_c1_reductor_no_debe_fugar():
    """C1 (pendiente): pedir 3/16 no debería devolver el reductor 1/4 x 3/16."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA JIC", medida="3/16", angulo="90")
    assert r.empty


def test_c1_medida_uniforme_si_matchea():
    """Pedir 3/4 (que sí existe uniforme) debe encontrarlo."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA JIC", medida="3/4", angulo="90")
    assert sorted(r["codigo"].tolist()) == ["26791-12-12"]


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
