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
