import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..geo import calcular_paradas, codificar_polyline, decodificar_polyline, haversine_km
from ..models import RutaMaestra, Ubicacion
from ..osrm import OsrmNoDisponible, SinCarretera, consultar_osrm
from ..schemas import RutaMaestraCalcular, RutaMaestraLeer

router = APIRouter(prefix="/rutas-maestras", tags=["rutas-maestras"])

RADIO_PARADA_KM = 20.0            # ciudades a menos de esto de la carretera cuentan como paradas
FACTOR_SINUOSIDAD = 1.3           # para la estimación: la carretera es ~30 % más larga que la línea recta
VELOCIDAD_ESTIMADA_KMH = 60.0     # para la estimación de duración
REINTENTO_ESTIMADA = timedelta(minutes=10)  # cada cuánto se reintenta OSRM sobre una ruta estimada


def _resolver_ubicacion(db: Session, ubicacion_id, codigo, rol: str) -> Ubicacion:
    query = db.query(Ubicacion)
    if ubicacion_id is not None:
        query = query.filter(Ubicacion.id == ubicacion_id)
    else:
        query = query.filter(Ubicacion.codigo == codigo.strip().upper())
    ubicacion = query.first()
    if ubicacion is None:
        raise HTTPException(status_code=422, detail=f"La ubicación de {rol} no existe en el catálogo")
    if not ubicacion.activo:
        raise HTTPException(status_code=422, detail=f"La ubicación de {rol} ({ubicacion.nombre}) está inactiva")
    return ubicacion


def _buscar_par(db: Session, origen_id, destino_id):
    return (
        db.query(RutaMaestra)
        .filter(RutaMaestra.origen_id == origen_id, RutaMaestra.destino_id == destino_id)
        .first()
    )


def _ruta_osrm(db: Session, origen: Ubicacion, destino: Ubicacion) -> dict:
    """Ruta real por carretera. Lanza OsrmNoDisponible si OSRM no responde,
    o HTTPException 422 si OSRM confirma que no hay carretera."""
    try:
        r = consultar_osrm(float(origen.longitud), float(origen.latitud), float(destino.longitud), float(destino.latitud))
    except SinCarretera:
        raise HTTPException(
            status_code=422,
            detail={
                "codigo": "SIN_CARRETERA",
                "mensaje": f"No existe una ruta por carretera entre {origen.etiqueta} y {destino.etiqueta}",
            },
        )
    puntos = decodificar_polyline(r["geometria"])
    candidatas = (
        db.query(Ubicacion)
        .filter(Ubicacion.activo.is_(True), Ubicacion.id.not_in([origen.id, destino.id]))
        .all()
    )
    paradas = calcular_paradas(puntos, r["distancia_km"], candidatas, RADIO_PARADA_KM)
    return {
        "distancia_km": round(r["distancia_km"], 2),
        "duracion_horas": round(r["duracion_horas"], 2),
        "geometria": r["geometria"],
        "paradas": paradas,
        "fuente": "osrm",
    }


def _ruta_estimada(origen: Ubicacion, destino: Ubicacion) -> dict:
    """Plan B cuando OSRM no está disponible: línea recta corregida por un factor de sinuosidad."""
    recta = haversine_km(float(origen.latitud), float(origen.longitud), float(destino.latitud), float(destino.longitud))
    distancia = recta * FACTOR_SINUOSIDAD
    return {
        "distancia_km": round(distancia, 2),
        "duracion_horas": round(distancia / VELOCIDAD_ESTIMADA_KMH, 2),
        "geometria": codificar_polyline([
            (float(origen.latitud), float(origen.longitud)),
            (float(destino.latitud), float(destino.longitud)),
        ]),
        "paradas": [],
        "fuente": "estimada",
    }


def _aplicar(ruta: RutaMaestra, datos: dict) -> None:
    ruta.distancia_km = datos["distancia_km"]
    ruta.duracion_horas = datos["duracion_horas"]
    ruta.geometria = datos["geometria"]
    ruta.paradas = datos["paradas"]
    ruta.fuente = datos["fuente"]


def _obtener_o_404(db: Session, ruta_id: uuid.UUID) -> RutaMaestra:
    ruta = db.query(RutaMaestra).filter(RutaMaestra.id == ruta_id).first()
    if ruta is None:
        raise HTTPException(status_code=404, detail="Ruta maestra no encontrada")
    return ruta


@router.post("/calcular", response_model=RutaMaestraLeer, status_code=201)
def calcular_ruta_maestra(payload: RutaMaestraCalcular, response: Response, db: Session = Depends(get_db)):
    """Devuelve la ruta maestra del par origen→destino; si no existe, la calcula y la guarda.
    201 = recién calculada, 200 = ya existía y se reutiliza."""
    origen = _resolver_ubicacion(db, payload.origen_id, payload.origen_codigo, "origen")
    destino = _resolver_ubicacion(db, payload.destino_id, payload.destino_codigo, "destino")
    if origen.id == destino.id:
        raise HTTPException(status_code=422, detail="El origen y el destino son la misma ubicación")

    existente = _buscar_par(db, origen.id, destino.id)
    if existente is not None:
        response.status_code = 200
        ahora = datetime.now(timezone.utc)
        if existente.fuente == "osrm" or ahora - existente.actualizado_en < REINTENTO_ESTIMADA:
            return existente

    try:
        datos = _ruta_osrm(db, origen, destino)
    except OsrmNoDisponible:
        if existente is not None:
            return existente
        datos = _ruta_estimada(origen, destino)

    if existente is not None:
        _aplicar(existente, datos)
        db.commit()
        db.refresh(existente)
        return existente

    ruta = RutaMaestra(origen_id=origen.id, destino_id=destino.id)
    _aplicar(ruta, datos)
    db.add(ruta)
    try:
        db.commit()
    except IntegrityError:
        # Otra petición calculó el mismo par al mismo tiempo: se reutiliza la suya
        db.rollback()
        ya_creada = _buscar_par(db, origen.id, destino.id)
        if ya_creada is not None:
            response.status_code = 200
            return ya_creada
        raise HTTPException(status_code=409, detail="No se pudo guardar la ruta maestra")
    db.refresh(ruta)
    return ruta


@router.get("/", response_model=list[RutaMaestraLeer])
def listar_rutas_maestras(
    origen_codigo: Optional[str] = None,
    destino_codigo: Optional[str] = None,
    fuente: Optional[str] = None,
    limite: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(RutaMaestra)
    if origen_codigo:
        query = query.filter(RutaMaestra.origen_id.in_(
            db.query(Ubicacion.id).filter(Ubicacion.codigo == origen_codigo.strip().upper())))
    if destino_codigo:
        query = query.filter(RutaMaestra.destino_id.in_(
            db.query(Ubicacion.id).filter(Ubicacion.codigo == destino_codigo.strip().upper())))
    if fuente:
        query = query.filter(RutaMaestra.fuente == fuente.strip().lower())
    return query.order_by(RutaMaestra.calculada_en.desc()).limit(limite).all()


@router.get("/codigo/{codigo_ruta}", response_model=RutaMaestraLeer)
def obtener_ruta_maestra_por_codigo(codigo_ruta: str, db: Session = Depends(get_db)):
    ruta = db.query(RutaMaestra).filter(RutaMaestra.codigo_ruta == codigo_ruta.strip().upper()).first()
    if ruta is None:
        raise HTTPException(status_code=404, detail="Ruta maestra no encontrada")
    return ruta


@router.get("/{ruta_id}", response_model=RutaMaestraLeer)
def obtener_ruta_maestra(ruta_id: uuid.UUID, db: Session = Depends(get_db)):
    return _obtener_o_404(db, ruta_id)


@router.get("/{ruta_id}/geometria")
def obtener_geometria(ruta_id: uuid.UUID, db: Session = Depends(get_db)):
    """Trazado de la ruta para dibujarlo en el mapa: polyline codificada y lista de puntos [lat, lon]."""
    ruta = _obtener_o_404(db, ruta_id)
    puntos = decodificar_polyline(ruta.geometria)
    return {
        "codigo_ruta": ruta.codigo_ruta,
        "fuente": ruta.fuente,
        "num_puntos": len(puntos),
        "polyline": ruta.geometria,
        "puntos": [[lat, lon] for lat, lon in puntos],
    }


@router.post("/{ruta_id}/recalcular", response_model=RutaMaestraLeer)
def recalcular_ruta_maestra(ruta_id: uuid.UUID, db: Session = Depends(get_db)):
    """Vuelve a consultar OSRM y reemplaza los datos (por ejemplo, para mejorar una ruta estimada)."""
    ruta = _obtener_o_404(db, ruta_id)
    try:
        datos = _ruta_osrm(db, ruta.origen, ruta.destino)
    except OsrmNoDisponible as exc:
        raise HTTPException(status_code=503, detail=f"OSRM no está disponible en este momento: {exc}")
    _aplicar(ruta, datos)
    db.commit()
    db.refresh(ruta)
    return ruta