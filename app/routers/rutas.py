import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Ruta, HistorialRuta
from ..schemas import RutaCrear, RutaLeer, RutaRecalcular, HistorialRutaLeer

router = APIRouter(prefix="/rutas", tags=["rutas"])


def _obtener_ruta_o_404(db: Session, ruta_id: uuid.UUID) -> Ruta:
    ruta = db.query(Ruta).filter(Ruta.id == ruta_id).first()
    if ruta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ruta no encontrada")
    return ruta


@router.post("/", response_model=RutaLeer, status_code=status.HTTP_201_CREATED)
def crear_ruta(payload: RutaCrear, db: Session = Depends(get_db)):
    ruta = Ruta(**payload.model_dump())
    db.add(ruta)
    db.commit()
    db.refresh(ruta)
    return ruta


@router.get("/", response_model=list[RutaLeer])
def listar_rutas(envio_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    query = db.query(Ruta)
    if envio_id:
        query = query.filter(Ruta.envio_id == envio_id)
    return query.order_by(Ruta.creado_en.desc()).all()


@router.get("/{ruta_id}", response_model=RutaLeer)
def obtener_ruta(ruta_id: uuid.UUID, db: Session = Depends(get_db)):
    return _obtener_ruta_o_404(db, ruta_id)


@router.get("/{ruta_id}/historial", response_model=list[HistorialRutaLeer])
def obtener_historial_ruta(ruta_id: uuid.UUID, db: Session = Depends(get_db)):
    _obtener_ruta_o_404(db, ruta_id)
    return (
        db.query(HistorialRuta)
        .filter(HistorialRuta.ruta_id == ruta_id)
        .order_by(HistorialRuta.recalculado_en.desc())
        .all()
    )


@router.patch("/{ruta_id}/recalcular", response_model=RutaLeer)
def recalcular_ruta(ruta_id: uuid.UUID, payload: RutaRecalcular, db: Session = Depends(get_db)):
    ruta = _obtener_ruta_o_404(db, ruta_id)

    db.add(HistorialRuta(
        ruta_id=ruta.id,
        paradas_anteriores=ruta.paradas,
        distancia_km_anterior=ruta.distancia_km,
        hora_estimada_llegada_anterior=ruta.hora_estimada_llegada,
        motivo_recalculo=payload.motivo_recalculo,
    ))

    if payload.paradas is not None:
        ruta.paradas = payload.paradas
    if payload.distancia_km is not None:
        ruta.distancia_km = payload.distancia_km
    if payload.hora_estimada_llegada is not None:
        ruta.hora_estimada_llegada = payload.hora_estimada_llegada
    ruta.veces_recalculada += 1

    db.commit()
    db.refresh(ruta)
    return ruta