"""Tramo en vacío (reposicionamiento): del lugar donde está el vehículo hasta el origen del envío.

Se intenta por carretera con OSRM; si OSRM no responde se estima (línea recta x factor de sinuosidad) y el resultado
lo dice con `fuente: "estimada"`. Nunca se inventa una ubicación de partida: sin punto de partida no hay tramo.
"""
import asyncio
import os

from .geo import codificar_polyline, haversine_km
from .osrm import OsrmNoDisponible, SinCarretera, consultar_osrm

FACTOR_SINUOSIDAD = 1.3
VELOCIDAD_ESTIMADA_KMH = 60.0


def umbral_mismo_lugar_km() -> float:
    """Por debajo de esta distancia en línea recta el vehículo ya está en el origen: no hay tramo que simular."""
    return float(os.getenv("UMBRAL_MISMO_LUGAR_KM", "2"))


def calcular_tramo(desde: dict, hasta: dict) -> dict:
    """`desde` y `hasta` traen latitud/longitud. Devuelve distancia, duración, geometría (polyline) y fuente.
    Lanza SinCarretera si OSRM confirma que no hay camino."""
    lat1, lon1 = float(desde["latitud"]), float(desde["longitud"])
    lat2, lon2 = float(hasta["latitud"]), float(hasta["longitud"])
    recta = haversine_km(lat1, lon1, lat2, lon2)
    if recta < umbral_mismo_lugar_km():
        return {"distancia_km": 0.0, "duracion_horas": 0.0, "geometria": None, "fuente": "mismo_lugar",
                "linea_recta_km": round(recta, 2)}
    try:
        r = consultar_osrm(
            lon1, lat1, lon2, lat2,
            intentos=int(os.getenv("OSRM_INTENTOS_REPOSICION", "2")),
            timeout=float(os.getenv("OSRM_TIMEOUT_REPOSICION_S", "10")),
        )
        return {
            "distancia_km": round(r["distancia_km"], 2),
            "duracion_horas": round(r["duracion_horas"], 2),
            "geometria": r["geometria"],
            "fuente": "osrm",
            "linea_recta_km": round(recta, 2),
        }
    except SinCarretera:
        raise
    except OsrmNoDisponible:
        distancia = recta * FACTOR_SINUOSIDAD
        return {
            "distancia_km": round(distancia, 2),
            "duracion_horas": round(distancia / VELOCIDAD_ESTIMADA_KMH, 2),
            "geometria": codificar_polyline([(lat1, lon1), (lat2, lon2)]),
            "fuente": "estimada",
            "linea_recta_km": round(recta, 2),
        }


async def calcular_tramo_async(desde: dict, hasta: dict) -> dict:
    """OSRM es síncrono y lento: se ejecuta en un hilo para no congelar el servicio."""
    return await asyncio.to_thread(calcular_tramo, desde, hasta)
