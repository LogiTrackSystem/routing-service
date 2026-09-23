from pydantic import BaseModel, ConfigDict
from uuid import UUID
from decimal import Decimal
from datetime import datetime
from typing import Optional, Any


class RutaCrear(BaseModel):
    envio_id: UUID
    vehiculo_id: Optional[UUID] = None
    paradas: Optional[list[dict]] = None
    distancia_km: Optional[Decimal] = None
    hora_estimada_llegada: Optional[datetime] = None


class RutaRecalcular(BaseModel):
    paradas: Optional[list[dict]] = None
    distancia_km: Optional[Decimal] = None
    hora_estimada_llegada: Optional[datetime] = None
    motivo_recalculo: str


class RutaLeer(BaseModel):
    id: UUID
    envio_id: UUID
    vehiculo_id: Optional[UUID] = None
    paradas: Optional[Any] = None
    distancia_km: Optional[Decimal] = None
    hora_estimada_llegada: Optional[datetime] = None
    veces_recalculada: int
    creado_en: datetime
    actualizado_en: datetime
    model_config = ConfigDict(from_attributes=True)


class HistorialRutaLeer(BaseModel):
    id: UUID
    ruta_id: UUID
    paradas_anteriores: Optional[Any] = None
    distancia_km_anterior: Optional[Decimal] = None
    hora_estimada_llegada_anterior: Optional[datetime] = None
    motivo_recalculo: Optional[str] = None
    recalculado_en: datetime
    model_config = ConfigDict(from_attributes=True)