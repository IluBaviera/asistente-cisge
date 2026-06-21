"""Configuración de pytest para asistente-cisge.

Estrategia: importar los módulos de `app/` sin tocar la red ni OpenAI, y
proveer un DataFrame sintético que se inyecta en `motor.df` vía monkeypatch.
Así las pruebas son deterministas y corren offline, sin cambiar producción.
"""
import os
import pytest

# 1) OpenAI: clave dummy para que AsyncOpenAI() se construya sin error al
#    importar app.agente (la clave real nunca se usa en tests).
os.environ.setdefault("OPENAI_API_KEY", "test-key")

# 2) Evitar la carga de catálogo por red en el import de app.motor:
#    se sustituye httpx.get por un stub que devuelve {"productos": []} (carga
#    instantánea, df vacío). Se restaura inmediatamente después del import.
import httpx as _httpx


class _FakeResp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"productos": []}


_orig_get = _httpx.get
_httpx.get = lambda *a, **k: _FakeResp()
try:
    import app.motor as motor          # noqa: E402  (import tras el stub, a propósito)
    import app.agente as agente        # noqa: E402,F401
finally:
    _httpx.get = _orig_get


# ── Payload sintético: ~14 productos representativos ─────────────────────────
def _prod(codigo, grupo, descripcion, marca, subfamilia, precio=10.0,
          almacenes=None, unidad="UND",
          med_manguera="", med_rosca_1="", med_rosca_2="", med_tubo=""):
    return {
        "codigo": codigo,
        "codigo_interno": codigo,
        "descripcion": descripcion,
        "marca": marca,
        "precio": precio,
        "unidad": unidad,
        "almacenes": almacenes if almacenes is not None else {"Almacen Lima Centro": 10},
        "subfamilia": subfamilia,
        "grupo": grupo,
        "med_manguera": med_manguera,
        "med_rosca_1": med_rosca_1,
        "med_rosca_2": med_rosca_2,
        "med_tubo": med_tubo,
    }


_PAYLOAD = {"productos": [
    # ── ESPIGA 90° HEMBRA JIC R2 (para C1 y test de ángulo) ──────────────────
    _prod("26791-04-04", "ESPIGA 90° HEMBRA JIC R2",
          'espiga hembra jic 90° r1 / r2  1/4" x 1/4"', "LT", "ESPIGAS I",
          med_rosca_1="1/4", med_manguera="1/4"),
    _prod("26791-04-03", "ESPIGA 90° HEMBRA JIC R2",
          'espiga hembra jic 90° r1 / r2  1/4" x 3/16"', "LT", "ESPIGAS I",
          med_rosca_1="1/4", med_manguera="3/16"),   # reductor poblado
    _prod("26791-12-12", "ESPIGA 90° HEMBRA JIC R2",
          'espiga hembra jic 90° r2 / r12  3/4" x 3/4"', "LT", "ESPIGAS I",
          med_rosca_1="3/4", med_manguera="3/4"),
    # ── ESPIGA HEMBRA JIC R2 recta (sin ángulo) ─────────────────────────────
    _prod("24791-12-12", "ESPIGA HEMBRA JIC R2",
          'espiga hembra jic r2 / r12  3/4" x 3/4"', "LT", "ESPIGAS I"),
    # ── ESPIGA 90° HEMBRA MM PESADA R2 (para C2): NO existe M12, mínimo M14 ──
    _prod("20591T-14-04", "ESPIGA 90° HEMBRA MM PESADA R2",
          'espiga 90° hembra metrica pesada r2 / r12  m14 x 1/4"', "LT", "ESPIGAS I"),
    _prod("20591T-24-08", "ESPIGA 90° HEMBRA MM PESADA R2",
          'espiga 90° hembra metrica pesada r2 / r12  m24 x 1/2"', "LT", "ESPIGAS I"),
    # ── FERRULA R2: variante T/M y variante lisa ────────────────────────────
    _prod("03310-08", "FERRULA R2 T/M", 'ferrula r2 at/2sn t/m 1/2"', "LT", "FERRULAS"),
    _prod("00210-08", "FERRULA R2", 'ferrula r2 lisa 1/2"', "LT", "FERRULAS"),
    # ── ADAP multi-marca (mismo código, dos marcas) ─────────────────────────
    _prod("045-08-06", "ADAP MACHO JIC X HEMBRA NPT",
          'adap m jic - h npt 1/2" x 3/8"', "DME", "ADAPTADORES I"),
    _prod("045-08-06", "ADAP MACHO JIC X HEMBRA NPT",
          'adap m jic - h npt 1/2" x 3/8"', "LT", "ADAPTADORES I"),
    # ── ADAP con BSPP (para equivalencia BSP↔BSPP) ──────────────────────────
    _prod("050-08-08", "ADAP MACHO JIC X MACHO BSPP",
          'adap m jic - m bspp 1/2" x 1/2"', "DME", "ADAPTADORES I"),
    # ── Manguera R1 (tipo_cod fallback) ─────────────────────────────────────
    _prod("QF-R1-08", "R1", 'mang hidraulica r1 1/2" qf', "QF", "MANGUERAS HIDRAULICAS"),
    # ── ADAP 90° JIC×JIC (generico para tests de marca / angulo) ────
    _prod("099-16-16", "ADAP 90° MACHO JIC X HEMBRA JIC",
          'adap 90 m jic x h jic 1" x 1"', "DME", "ADAPTADORES I"),
    # ── BUSHING reductor M JIC 1 1/4 x H JIC 1 (caso "bushing 20 mj -16 fj") ──
    _prod("2215-20-16", "BUSHING MACHO JIC X HEMBRA JIC",
          'bushing m jic 1 1/4" x h jic 1"', "LT", "ADAPTADORES I"),
    _prod("2215-12-08", "BUSHING MACHO JIC X HEMBRA JIC",
          'bushing m jic 3/4" x h jic 1/2"', "LT", "ADAPTADORES I"),
    # ── Métricas 90° liviana pobladas (med_tubo) para test de búsqueda por tubo ──
    _prod("20491T-22-08", "ESPIGA 90° HEMBRA MM LIVIANA R2",
          'espiga 90° hembra metrica liviana r2 / r12 m22 x 1/2"', "LT", "ESPIGAS I",
          med_rosca_1="M22x1.5", med_manguera="1/2", med_tubo="15"),
    _prod("20491T-22-06", "ESPIGA 90° HEMBRA MM LIVIANA R2",
          'espiga 90° hembra metrica liviana r2 / r12 m22 x 3/8"', "LT", "ESPIGAS I",
          med_rosca_1="M22x1.5", med_manguera="3/8", med_tubo="15"),
    _prod("20491T-18-08", "ESPIGA 90° HEMBRA MM LIVIANA R2",
          'espiga 90° hembra metrica liviana r2 / r12 m18 x 1/2"', "LT", "ESPIGAS I",
          med_rosca_1="M18x1.5", med_manguera="1/2", med_tubo="12"),
]}


@pytest.fixture
def df_sintetico():
    """DataFrame construido con el pipeline real (_build_df_from_api)."""
    return motor._build_df_from_api(_PAYLOAD)


@pytest.fixture(autouse=True)
def _inyectar_df(monkeypatch, df_sintetico):
    """Reemplaza el catálogo global del motor por el sintético en cada test."""
    monkeypatch.setattr(motor, "df", df_sintetico)


@pytest.fixture
def motor_mod():
    return motor


@pytest.fixture
def agente_mod():
    return agente
