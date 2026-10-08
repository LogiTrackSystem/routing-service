import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..asignacion import ESTADOS_FUERA_DE_SAGA, intentar_asignar, reintentar_pendientes
from ..database import get_db
from ..models import Ruta
from ..schemas import RutaLeer

router = APIRouter(prefix="/asignaciones", tags=["asignaciones"])


@router.post("/reintentar")
async def reintentar_todas():
    """Fuerza ahora un barrido: reasigna lo que está sin asignación, libera lo pendiente y publica eventos."""
    return await reintentar_pendientes(forzar=True)


@router.post("/envio/{envio_id}/reintentar", response_model=RutaLeer)
async def reintentar_envio(envio_id: uuid.UUID, db: Session = Depends(get_db)):
    ruta = (
        db.query(Ruta)
        .filter(Ruta.envio_id == envio_id, Ruta.estado.not_in(ESTADOS_FUERA_DE_SAGA))
        .order_by(Ruta.creado_en.desc())
        .first()
    )
    if ruta is None:
        raise HTTPException(status_code=404, detail="Ese envío no tiene una solicitud de asignación")
    await intentar_asignar(ruta.id)
    db.refresh(ruta)
    return ruta