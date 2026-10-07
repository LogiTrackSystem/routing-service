import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Ubicacion
from ..schemas import UbicacionActualizar, UbicacionCrear, UbicacionLeer
from ..texto import normalizar

router = APIRouter(prefix="/ubicaciones", tags=["ubicaciones"])


def _generar_codigo(db: Session, codigo_pais: str, nombre_normalizado: str) -> str:
    letras = "".join(c for c in nombre_normalizado if c.isalpha()).upper()[:3].ljust(3, "X")
    base = f"{codigo_pais}-{letras}"
    codigo, n = base, 1
    while db.query(Ubicacion.id).filter(Ubicacion.codigo == codigo).first():
        n += 1
        codigo = f"{base}{n}"
    return codigo


@router.get("/", response_model=list[UbicacionLeer])
def buscar_ubicaciones(
    q: Optional[str] = None,
    pais: Optional[str] = None,
    tipo: Optional[str] = None,
    incluir_inactivas: bool = False,
    limite: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Autocompletado: q busca por nombre (sin importar tildes ni mayúsculas) o por código.
    Los que empiezan por lo escrito salen primero."""
    query = db.query(Ubicacion)
    if not incluir_inactivas:
        query = query.filter(Ubicacion.activo.is_(True))
    if pais:
        query = query.filter(Ubicacion.codigo_pais == pais.strip().upper())
    if tipo:
        query = query.filter(Ubicacion.tipo == tipo.strip().lower())

    orden = [Ubicacion.nombre.asc()]
    if q and q.strip():
        texto = normalizar(q).replace("%", "").replace("_", "")
        query = query.filter(
            or_(
                Ubicacion.nombre_normalizado.like(f"%{texto}%"),
                Ubicacion.codigo.ilike(f"{q.strip()}%"),
            )
        )
        empieza_por = case((Ubicacion.nombre_normalizado.like(f"{texto}%"), 0), else_=1)
        orden = [empieza_por, Ubicacion.nombre.asc()]
    return query.order_by(*orden).limit(limite).all()


@router.get("/paises")
def listar_paises(db: Session = Depends(get_db)):
    """Países que tienen ubicaciones activas, para filtros del frontend."""
    filas = (
        db.query(Ubicacion.codigo_pais, Ubicacion.pais, func.count(Ubicacion.id))
        .filter(Ubicacion.activo.is_(True))
        .group_by(Ubicacion.codigo_pais, Ubicacion.pais)
        .order_by(Ubicacion.pais.asc())
        .all()
    )
    return [{"codigo_pais": c, "pais": p, "total": n} for c, p, n in filas]


@router.post("/", response_model=UbicacionLeer, status_code=201)
def crear_ubicacion(payload: UbicacionCrear, db: Session = Depends(get_db)):
    nombre_norm = normalizar(payload.nombre)
    ubicacion = Ubicacion(
        codigo=payload.codigo or _generar_codigo(db, payload.codigo_pais, nombre_norm),
        nombre=payload.nombre,
        nombre_normalizado=nombre_norm,
        departamento=payload.departamento,
        pais=payload.pais,
        codigo_pais=payload.codigo_pais,
        latitud=payload.latitud,
        longitud=payload.longitud,
        tipo=payload.tipo,
    )
    db.add(ubicacion)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ya existe esa ubicación (mismo país, nombre y departamento) o el código está repetido",
        )
    db.refresh(ubicacion)
    return ubicacion


@router.get("/codigo/{codigo}", response_model=UbicacionLeer)
def obtener_ubicacion_por_codigo(codigo: str, db: Session = Depends(get_db)):
    ubicacion = db.query(Ubicacion).filter(Ubicacion.codigo == codigo.strip().upper()).first()
    if ubicacion is None:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    return ubicacion


@router.get("/{ubicacion_id}", response_model=UbicacionLeer)
def obtener_ubicacion(ubicacion_id: uuid.UUID, db: Session = Depends(get_db)):
    ubicacion = db.query(Ubicacion).filter(Ubicacion.id == ubicacion_id).first()
    if ubicacion is None:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    return ubicacion


@router.patch("/{ubicacion_id}", response_model=UbicacionLeer)
def actualizar_ubicacion(ubicacion_id: uuid.UUID, payload: UbicacionActualizar, db: Session = Depends(get_db)):
    ubicacion = db.query(Ubicacion).filter(Ubicacion.id == ubicacion_id).first()
    if ubicacion is None:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        if valor is not None:
            setattr(ubicacion, campo, valor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una ubicación con ese departamento")
    db.refresh(ubicacion)
    return ubicacion