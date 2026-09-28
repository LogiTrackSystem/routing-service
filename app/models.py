import uuid
from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from .database import Base


class Ruta(Base):
    __tablename__ = "rutas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    envio_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    vehiculo_id = Column(UUID(as_uuid=True), nullable=True)
    kilometraje_inicio_ruta = Column(Numeric(10, 2), nullable=True)
    paradas = Column(JSONB, nullable=True)
    distancia_km = Column(Numeric(10, 2), nullable=True)
    hora_estimada_llegada = Column(DateTime(timezone=True), nullable=True)
    veces_recalculada = Column(Integer, nullable=False, default=0)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class HistorialRuta(Base):
    __tablename__ = "historial_rutas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ruta_id = Column(UUID(as_uuid=True), ForeignKey("rutas.id"), nullable=False, index=True)
    paradas_anteriores = Column(JSONB, nullable=True)
    distancia_km_anterior = Column(Numeric(10, 2), nullable=True)
    hora_estimada_llegada_anterior = Column(DateTime(timezone=True), nullable=True)
    motivo_recalculo = Column(Text, nullable=True)
    recalculado_en = Column(DateTime(timezone=True), server_default=func.now())