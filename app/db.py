import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=192.168.2.13;"
    "DATABASE=BdAsistente;"
    f"UID=cisge_asistente;"
    f"PWD={os.getenv('DB_PASSWORD', '')};"
)


def _get_conn():
    import pyodbc
    return pyodbc.connect(_CONN_STR, timeout=5)


def cargar_historial(numero_wa: str) -> list:
    """Últimos 10 mensajes del número. Devuelve [] si la BD falla o el último
    mensaje tiene más de 2 horas de antigüedad (sesión expirada)."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT TOP 10 rol, contenido, timestamp
                FROM Conversacion
                WHERE numero_wa = ?
                ORDER BY timestamp DESC
                """,
                numero_wa,
            )
            filas = cur.fetchall()

        if not filas:
            return []

        # filas vienen DESC; el primero es el más reciente
        mas_reciente = filas[0][2]
        if isinstance(mas_reciente, str):
            mas_reciente = datetime.fromisoformat(mas_reciente)
        if datetime.utcnow() - mas_reciente > timedelta(hours=2):
            return []

        # Reordenar ASC para el historial del agente
        return [{"role": f["rol"], "content": f["contenido"]}
                for f in reversed([{"rol": r, "contenido": c} for r, c, _ in filas])]

    except Exception as e:
        logger.warning(f"db.cargar_historial falló para {numero_wa}: {e}")
        return []


def guardar_mensajes(numero_wa: str, user_msg: str, assistant_msg: str) -> None:
    """Inserta fila user y fila assistant en Conversacion. Falla silenciosamente."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            ahora = datetime.utcnow()
            cur.execute(
                "INSERT INTO Conversacion (numero_wa, rol, contenido, timestamp) VALUES (?, ?, ?, ?)",
                numero_wa, "user", user_msg, ahora,
            )
            cur.execute(
                "INSERT INTO Conversacion (numero_wa, rol, contenido, timestamp) VALUES (?, ?, ?, ?)",
                numero_wa, "assistant", assistant_msg, ahora,
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"db.guardar_mensajes falló para {numero_wa}: {e}")
