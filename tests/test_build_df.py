"""Tests de _build_df_from_api: normalización de encoding y extracción de medidas."""
import app.motor as motor


def _build(productos):
    return motor._build_df_from_api({"productos": productos})


def _row(productos, codigo):
    df = _build(productos)
    return df[df["codigo"] == codigo].iloc[0]


# ── B2: normalización de encoding del campo grupo ────────────────────────────

def test_grupo_normaliza_ufffd_y_nbsp():
    """U+FFFD → grado, NBSP → espacio, y strip/upper. (escapes explícitos)."""
    grupo_crudo = "ADAP 90\ufffd MACHO JIC X HEMBRA JIC\xa0"
    fila = _row([{
        "codigo": "099-16-16", "descripcion": "adap", "marca": "DME",
        "precio": 10.0, "unidad": "UND", "almacenes": {},
        "subfamilia": "ADAPTADORES I", "grupo": grupo_crudo,
    }], "099-16-16")
    assert fila["grupo"] == "ADAP 90° MACHO JIC X HEMBRA JIC"
    assert "\ufffd" not in fila["grupo"]
    assert "\xa0" not in fila["grupo"]


# ── Extracción de medidas desde el código ────────────────────────────────────

def test_medidas_cod_reductor():
    fila = _row([{
        "codigo": "26791-04-03", "descripcion": 'espiga 1/4" x 3/16"', "marca": "LT",
        "precio": 5.0, "unidad": "UND", "almacenes": {}, "subfamilia": "ESPIGAS I",
        "grupo": "ESPIGA 90° HEMBRA JIC R2",
    }], "26791-04-03")
    assert fila["medidas_cod"] == ["1/4", "3/16"]
    assert fila["medida_cod"] == "03"


# ── dropna: productos sin precio se descartan ────────────────────────────────

def test_producto_sin_precio_se_descarta():
    df = _build([
        {"codigo": "AAA-04", "descripcion": "x", "marca": "LT", "precio": None,
         "unidad": "UND", "almacenes": {}, "subfamilia": "ESPIGAS I", "grupo": "X"},
        {"codigo": "BBB-04", "descripcion": "y", "marca": "LT", "precio": 9.0,
         "unidad": "UND", "almacenes": {}, "subfamilia": "ESPIGAS I", "grupo": "Y"},
    ])
    assert "AAA-04" not in df["codigo"].tolist()
    assert "BBB-04" in df["codigo"].tolist()
