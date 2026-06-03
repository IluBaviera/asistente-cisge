import logging
import httpx
from app.motor import consultar, cotizar_multiple

logger = logging.getLogger(__name__)

STOCK_API = "https://api.comercialcisgesac.com.pe/stock"


def tool_buscar_producto(query: str) -> str:
    """Busca un producto por código, tipo+medida o descripción."""
    logger.info(f"tool_buscar_producto → consultar({query!r})")
    _, respuesta = consultar(query)
    return respuesta


def tool_ver_stock(codigo: str, almacen: str = None) -> str:
    """Consulta stock en tiempo real para un código. Filtra por almacén si se indica."""
    try:
        r = httpx.get(STOCK_API, timeout=5)
        r.raise_for_status()
        data = r.json()
        productos = data.get("productos", [])
        coincidencias = [p for p in productos if str(p.get("codigo", "")).upper() == codigo.upper()]
        if not coincidencias:
            return f"No se encontró stock para el código {codigo}."
        lineas = []
        for p in coincidencias:
            marca = p.get("marca", "")
            almacenes = p.get("almacenes") or {}
            if almacen:
                almacenes = {k: v for k, v in almacenes.items()
                             if almacen.lower() in k.lower()}
            con_stock = {k: v for k, v in almacenes.items() if v > 0}
            if not con_stock:
                lineas.append(f"{codigo} ({marca}): AGOTADO")
            else:
                partes = ", ".join(f"{k.replace('Almacen ', '')}: {v:.0f}" for k, v in con_stock.items())
                lineas.append(f"{codigo} ({marca}): {partes} {p.get('unidad', '')}")
        return "\n".join(lineas)
    except Exception as e:
        logger.warning(f"tool_ver_stock error: {e}")
        return f"No se pudo consultar el stock en este momento."


def tool_generar_cotizacion(cliente: str, items: list) -> str:
    """Genera cotización para múltiples ítems. items: lista de strings (uno por línea)."""
    lineas = [str(it) for it in items]
    cotizacion = cotizar_multiple(lineas)
    if cliente:
        cotizacion = f"Cotización para {cliente}:\n\n" + cotizacion
    return cotizacion


# ── Definiciones de tools en formato OpenAI function calling ─────────────────

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "tool_buscar_producto",
            "description": (
                "Busca un producto en el catálogo CISGE por código exacto, prefijo, "
                "tipo+medida+marca o descripción libre. Devuelve precio, stock por almacén "
                "e IGV. Úsala cuando el vendedor pregunta por un producto específico."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Texto de búsqueda tal cual lo escribió el usuario: código (QF-R1-1/2\"), tipo+medida (R1 1/2 QF), descripción, etc. No reformatees ni traduzcas — pasa el texto original.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_ver_stock",
            "description": (
                "Consulta el stock actualizado de un código específico. "
                "Úsala cuando ya se conoce el código y el vendedor quiere saber disponibilidad."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo": {
                        "type": "string",
                        "description": "Código comercial exacto del producto (ej: QF-R1-1/2\").",
                    },
                    "almacen": {
                        "type": "string",
                        "description": "Filtrar por almacén (opcional): Lima Centro, Colonial, San Luis 1, San Luis 2.",
                    },
                },
                "required": ["codigo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_generar_cotizacion",
            "description": (
                "Genera una cotización formal con subtotal e IGV para varios productos. "
                "Úsala cuando el vendedor pide cotizar una lista de ítems."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cliente": {
                        "type": "string",
                        "description": "Nombre del cliente (puede ser vacío).",
                    },
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista de ítems a cotizar, uno por elemento (ej: [\"QF-R1-1/2\\\" x2\", \"R2 3/4 vitillo\"]).",
                    },
                },
                "required": ["cliente", "items"],
            },
        },
    },
]
