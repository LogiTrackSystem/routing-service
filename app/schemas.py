from pydantic import BaseModel, ConfigDict, Field, field_validator
from uuid import UUID
from decimal import Decimal
from datetime import datetime
from typing import Any, Literal, Optional


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



# ---------- Ubicaciones ----------

class UbicacionCrear(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=100)
    departamento: str = Field(..., min_length=2, max_length=100)
    pais: str = Field(..., min_length=2, max_length=60)
    codigo_pais: str = Field(..., min_length=2, max_length=2)
    latitud: float = Field(..., ge=-90, le=90)
    longitud: float = Field(..., ge=-180, le=180)
    tipo: Literal["ciudad", "capital", "puerto"] = "ciudad"
    codigo: Optional[str] = Field(None, min_length=3, max_length=12)

    @field_validator("nombre", "departamento", "pais")
    @classmethod
    def _limpiar(cls, v):
        return v.strip()

    @field_validator("codigo_pais", "codigo")
    @classmethod
    def _mayusculas(cls, v):
        return v.strip().upper() if v else v


class UbicacionActualizar(BaseModel):
    departamento: Optional[str] = Field(None, min_length=2, max_length=100)
    tipo: Optional[Literal["ciudad", "capital", "puerto"]] = None
    activo: Optional[bool] = None


class UbicacionLeer(BaseModel):
    id: UUID
    codigo: str
    nombre: str
    departamento: str
    pais: str
    codigo_pais: str
    latitud: float
    longitud: float
    tipo: str
    activo: bool
    etiqueta: str
    model_config = ConfigDict(from_attributes=True)