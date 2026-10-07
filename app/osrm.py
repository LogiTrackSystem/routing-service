import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
INTENTOS = 3
TIMEOUT_S = 25.0
CABECERAS = {"User-Agent": "LogiTrack-Routing/1.0 (proyecto academico)"}


class SinCarretera(Exception):
    """OSRM respondió que no existe camino por carretera entre los dos puntos."""


class OsrmNoDisponible(Exception):
    """No se pudo obtener una respuesta útil de OSRM (red caída, límite de uso, error del servidor)."""


def consultar_osrm(lon1, lat1, lon2, lat2) -> dict:
    url = f"{OSRM_URL}/route/v1/driving/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
    parametros = {"overview": "simplified", "geometries": "polyline", "steps": "false"}
    ultimo_error = "sin intentos"
    for intento in range(1, INTENTOS + 1):
        try:
            resp = httpx.get(url, params=parametros, headers=CABECERAS, timeout=TIMEOUT_S)
            datos = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            ultimo_error = f"{type(exc).__name__}: {exc}"
        else:
            codigo = datos.get("code")
            if codigo == "Ok" and datos.get("routes"):
                ruta = datos["routes"][0]
                return {
                    "distancia_km": ruta["distance"] / 1000.0,
                    "duracion_horas": ruta["duration"] / 3600.0,
                    "geometria": ruta["geometry"],
                }
            if codigo in ("NoRoute", "NoSegment"):
                raise SinCarretera(datos.get("message") or codigo)
            ultimo_error = f"OSRM respondió HTTP {resp.status_code} ({codigo})"
        if intento < INTENTOS:
            time.sleep(intento)  # espera 1 s y luego 2 s antes de reintentar
    raise OsrmNoDisponible(ultimo_error)