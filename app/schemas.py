from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
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
    estado: str
    vehiculo_id: Optional[UUID] = None
    conductor_id: Optional[UUID] = None
    detalle_asignacion: Optional[Any] = None
    ruta_maestra_id: Optional[UUID] = None
    codigo_ruta: Optional[str] = None
    paradas: Optional[Any] = None
    distancia_km: Optional[Decimal] = None
    distancia_planificada_km: Optional[Decimal] = None
    hora_estimada_llegada: Optional[datetime] = None
    veces_recalculada: int
    intentos: int
    ultimo_error: Optional[str] = None
    proximo_reintento_en: Optional[datetime] = None
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


# ---------- Rutas maestras ----------

class RutaMaestraCalcular(BaseModel):
    origen_id: Optional[UUID] = None
    origen_codigo: Optional[str] = None
    destino_id: Optional[UUID] = None
    destino_codigo: Optional[str] = None

    @model_validator(mode="after")
    def _origen_y_destino(self):
        if (self.origen_id is None) == (self.origen_codigo is None):
            raise ValueError("Indique el origen con origen_id o con origen_codigo (solo uno)")
        if (self.destino_id is None) == (self.destino_codigo is None):
            raise ValueError("Indique el destino con destino_id o con destino_codigo (solo uno)")
        return self


class RutaMaestraLeer(BaseModel):
    id: UUID
    codigo_ruta: str
    origen: UbicacionLeer
    destino: UbicacionLeer
    distancia_km: float
    duracion_horas: float
    fuente: str
    estimada: bool
    paradas: Optional[list[dict]] = None
    calculada_en: datetime
    actualizado_en: datetime
    model_config = ConfigDict(from_attributes=True)