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

@pytest.mark.xfail(reason="C1: exclusión de reductores es suave; 3/16 fuga a 1/4x3/16",
                   strict=False)
def test_c1_reductor_no_debe_fugar():
    """Pedir 3/16 (uniforme) no debe devolver el reductor 1/4 x 3/16."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA JIC", medida="3/16", angulo="90")
    assert r.empty


@pytest.mark.xfail(reason="C2: filtro métrico es suave; M12 inexistente cae a otra rosca",
                   strict=False)
def test_c2_rosca_metrica_inexistente_no_fallthrough():
    """Pedir M12 (no existe, mínimo es M14) no debe devolver M14/M24."""
    r = motor.buscar_por_tipo_medida_marca(tipo="ESPIGA HEMBRA MM PESADA", medida="M12", angulo="90")
    assert r.empty
