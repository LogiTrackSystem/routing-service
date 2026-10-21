"""Carga compartida: ¿puede este envío subirse a la ruta de un vehículo que ya va en camino?

Regla de la versión 1 (sin desvíos): solo se comparte si el origen Y el destino del nuevo envío son puntos que ya
están sobre la ruta del vehículo (su origen, su destino o una de sus paradas del catálogo), el destino viene DESPUÉS del
origen y el vehículo todavía no pasó por el punto de recogida. La capacidad (peso, volumen, tipo de carga) la valida
Fleet bajo candado; aquí solo se decide si el recorrido encaja.
"""
import os
from typing import Optional


def _num(nombre: str, defecto: float) -> float:
    try:
        return float(os.getenv(nombre, defecto))
    except ValueError:
        return defecto


def compartir_activo() -> bool:
    return os.getenv("CARGA_COMPARTIDA_ACTIVA", "true").strip().lower() not in ("0", "false", "no")


def desvio_maximo_km() -> float:
    """Una parada del catálogo cuenta como "sobre la ruta" si está a menos de esto de la carretera."""
    return _num("PARADA_MAX_DESVIO_KM", 5.0)


def margen_recogida_km() -> float:
    """Kilómetros de colchón: el vehículo tiene que estar al menos esto antes del punto de recogida."""
    return _num("MARGEN_RECOGIDA_KM", 15.0)


def tramo_minimo_km() -> float:
    return _num("TRAMO_MINIMO_COMPARTIDO_KM", 5.0)


def puntos_de_ruta(maestra) -> list[dict]:
    """Origen (km 0), paradas del catálogo (con su km y su desvío) y destino (km = distancia total)."""
    puntos = [{
        "ubicacion_id": str(maestra.origen_id), "nombre": maestra.origen.nombre if maestra.origen else None,
        "km": 0.0, "desvio_km": 0.0,
    }]
    for p in maestra.paradas or []:
        if p.get("ubicacion_id") is None or p.get("km_desde_origen") is None:
            continue
        puntos.append({
            "ubicacion_id": str(p["ubicacion_id"]), "nombre": p.get("nombre"),
            "km": float(p["km_desde_origen"]), "desvio_km": float(p.get("distancia_a_la_via_km") or 0.0),
        })
    puntos.append({
        "ubicacion_id": str(maestra.destino_id), "nombre": maestra.destino.nombre if maestra.destino else None,
        "km": float(maestra.distancia_km), "desvio_km": 0.0,
    })
    return puntos


def _buscar(puntos: list[dict], ubicacion_id: str, primero: bool) -> Optional[dict]:
    candidatos = [p for p in puntos if p["ubicacion_id"] == ubicacion_id and p["desvio_km"] <= desvio_maximo_km()]
    if not candidatos:
        return None
    return min(candidatos, key=lambda p: p["km"]) if primero else max(candidatos, key=lambda p: p["km"])


def evaluar(anfitrion, maestra_anfitriona, maestra_invitada) -> Optional[dict]:
    """Devuelve {km_recogida, km_entrega, recogida, entrega, progreso_km} si el recorrido encaja; None si no.
    `anfitrion` es la Ruta del vehículo en camino (estado asignada o en_curso)."""
    if maestra_anfitriona is None or maestra_invitada is None:
        return None
    puntos = puntos_de_ruta(maestra_anfitriona)
    recogida = _buscar(puntos, str(maestra_invitada.origen_id), primero=True)
    entrega = _buscar(puntos, str(maestra_invitada.destino_id), primero=False)
    if recogida is None or entrega is None:
        return None
    if entrega["km"] - recogida["km"] < tramo_minimo_km():
        return None  # el destino queda antes (o pegado) al origen: iría en sentido contrario
    progreso = 0.0
    if anfitrion.estado == "en_curso":
        progreso = float(anfitrion.distancia_km or 0.0)  # km reales recorridos con carga (odómetro)
        if recogida["km"] < progreso + margen_recogida_km():
            return None  # ya pasó (o está por pasar) por el punto de recogida
    return {
        "km_recogida": round(recogida["km"], 2),
        "km_entrega": round(entrega["km"], 2),
        "recogida": recogida["nombre"],
        "entrega": entrega["nombre"],
        "progreso_km": round(progreso, 2),
    }
