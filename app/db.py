import logging
import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.comercialcisgesac.com.pe"


def cargar_historial(numero_wa: str) -> list:
    try:
        r = httpx.post(f"{_BASE}/historial/cargar", json={"numero_wa": numero_wa}, timeout=5)
        r.raise_for_status()
        historial = r.json().get("historial", [])
        logger.info(f"db.cargar_historial [{numero_wa}]: {len(historial)} mensajes cargados")
        return historial
    except Exception as e:
        logger.warning(f"db.cargar_historial falló para {numero_wa}: {e}")
        return []


def cargar_vendedores() -> dict:
    """Devuelve {numero_wa: nombre} de los vendedores activos (tabla Vendedor
    vía API). Devuelve {} si falla — el llamador cae a la whitelist de env var."""
    try:
        r = httpx.get(f"{_BASE}/vendedores", timeout=5)
        r.raise_for_status()
        vendedores = r.json().get("vendedores", [])
        mapa = {v["numero_wa"]: v["nombre"] for v in vendedores if v.get("numero_wa")}
        logger.info(f"db.cargar_vendedores: {len(mapa)} vendedores activos")
        return mapa
    except Exception as e:
        logger.warning(f"db.cargar_vendedores falló: {e}")
        return {}


def guardar_mensajes(numero_wa: str, user_msg: str, assistant_msg: str) -> None:
    try:
        r = httpx.post(
            f"{_BASE}/historial/guardar",
            json={"numero_wa": numero_wa, "user_msg": user_msg, "assistant_msg": assistant_msg},
            timeout=5,
        )
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"db.guardar_mensajes falló para {numero_wa}: {e}")
