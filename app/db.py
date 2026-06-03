import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def _get_conn():
    import pymssql
    return pymssql.connect(
        server='192.168.2.13',
        user='cisge_asistente',
        password=os.getenv('DB_PASSWORD'),
        database='BdAsistente',
        timeout=5,
    )


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
            logger.info(f"db.cargar_historial [{numero_wa}]: 0 mensajes (sin historial)")
            return []

        # filas vienen DESC; el primero es el más reciente
        mas_reciente = filas[0][2]
        if isinstance(mas_reciente, str):
            mas_reciente = datetime.fromisoformat(mas_reciente)
        if datetime.utcnow() - mas_reciente > timedelta(hours=2):
            logger.info(f"db.cargar_historial [{numero_wa}]: sesión expirada (último msg hace >2h)")
            return []

        historial = [{"role": r, "content": c} for r, c, _ in reversed(filas)]
        logger.info(f"db.cargar_historial [{numero_wa}]: {len(historial)} mensajes cargados")
        return historial

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
