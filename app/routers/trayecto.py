from fastapi import APIRouter, HTTPException, Query

from ..osrm import SinCarretera
from ..trayecto import calcular_tramo_async

router = APIRouter(prefix="/trayecto", tags=["trayecto"])


@router.get("/")
async def trayecto(
    desde_lat: float = Query(..., ge=-90, le=90), desde_lon: float = Query(..., ge=-180, le=180),
    hasta_lat: float = Query(..., ge=-90, le=90), hasta_lon: float = Query(..., ge=-180, le=180),
):
    """Tramo por carretera entre dos puntos (lo usa Tracking para el recorrido en vacío cuando Fleet no conoce la
    ubicación del vehículo). `fuente` es "osrm" o "estimada" (línea recta x 1.3)."""
    try:
        return await calcular_tramo_async(
            {"latitud": desde_lat, "longitud": desde_lon}, {"latitud": hasta_lat, "longitud": hasta_lon})
    except SinCarretera as exc:
        raise HTTPException(status_code=422, detail={"codigo": "SIN_CARRETERA", "mensaje": str(exc)})
