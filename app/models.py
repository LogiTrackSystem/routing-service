import uuid
from sqlalchemy import Boolean, Column, Index, Integer, Numeric, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


class Ruta(Base):
    __tablename__ = "rutas"
    __table_args__ = (
        Index("uq_rutas_envio_vigente", "envio_id", unique=True,
              postgresql_where=text("estado NOT IN ('historica', 'manual')"),
              sqlite_where=text("estado NOT IN ('historica', 'manual')")),
        Index("ix_rutas_vehiculo_estado", "vehiculo_id", "estado"),
    )
    
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
    estado = Column(String(20), nullable=False, server_default="manual", index=True)
    conductor_id = Column(UUID(as_uuid=True), nullable=True)
    reserva_id = Column(UUID(as_uuid=True), nullable=True)
    ruta_maestra_id = Column(UUID(as_uuid=True), ForeignKey("rutas_maestras.id"), nullable=True)
    requisitos = Column(JSONB, nullable=True)
    detalle_asignacion = Column(JSONB, nullable=True)
    distancia_planificada_km = Column(Numeric(10, 2), nullable=True)
    intentos = Column(Integer, nullable=False, server_default="0")
    proximo_reintento_en = Column(DateTime(timezone=True), nullable=True)
    ultimo_error = Column(Text, nullable=True)
    evento_pendiente = Column(String(30), nullable=True)
    # Carga compartida: "exclusiva" = el vehículo sale solo para este envío; "compartida" = se sube a la ruta de otro
    modo = Column(String(12), nullable=False, server_default="exclusiva")
    ruta_anfitriona_id = Column(UUID(as_uuid=True), ForeignKey("rutas.id"), nullable=True, index=True)
    km_recogida = Column(Numeric(10, 2), nullable=True)   # km (sobre la ruta del anfitrión) donde sube la carga
    km_entrega = Column(Numeric(10, 2), nullable=True)    # km donde se baja
    # Tramo en vacío desde donde estaba el vehículo hasta el origen del envío (no se factura: no entra en distancia_km)
    reposicion = Column(JSONB, nullable=True)

    ruta_maestra = relationship("RutaMaestra")

    @property
    def reposicion_resumen(self):
        """El tramo en vacío sin la geometría (que es pesada y solo la usa Tracking)."""
        if not self.reposicion:
            return None
        return {k: v for k, v in self.reposicion.items() if k != "geometria"}

    @property
    def codigo_ruta(self):
        return self.ruta_maestra.codigo_ruta if self.ruta_maestra else None


class HistorialRuta(Base):
    __tablename__ = "historial_rutas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ruta_id = Column(UUID(as_uuid=True), ForeignKey("rutas.id"), nullable=False, index=True)
    paradas_anteriores = Column(JSONB, nullable=True)
    distancia_km_anterior = Column(Numeric(10, 2), nullable=True)
    hora_estimada_llegada_anterior = Column(DateTime(timezone=True), nullable=True)
    motivo_recalculo = Column(Text, nullable=True)
    recalculado_en = Column(DateTime(timezone=True), server_default=func.now())



class Ubicacion(Base):
    __tablename__ = "ubicaciones"
    __table_args__ = (
        UniqueConstraint("codigo_pais", "nombre_normalizado", "departamento", name="uq_ubicaciones_pais_nombre_depto"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo = Column(String(12), unique=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    nombre_normalizado = Column(String(100), nullable=False, index=True)
    departamento = Column(String(100), nullable=False)
    pais = Column(String(60), nullable=False)
    codigo_pais = Column(String(2), nullable=False, index=True)
    latitud = Column(Numeric(9, 6), nullable=False)
    longitud = Column(Numeric(9, 6), nullable=False)
    tipo = Column(String(20), nullable=False, server_default="ciudad")
    activo = Column(Boolean, nullable=False, server_default="true")
    creado_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    @property
    def etiqueta(self) -> str:
        partes = [self.nombre]
        if self.departamento and self.departamento.lower() != self.nombre.lower():
            partes.append(self.departamento)
        partes.append(self.pais)
        return ", ".join(partes)




class RutaMaestra(Base):
    __tablename__ = "rutas_maestras"
    __table_args__ = (UniqueConstraint("origen_id", "destino_id", name="uq_rutas_maestras_par"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo_ruta = Column(
        String(12),
        server_default=text("'RUT-' || lpad(nextval('seq_codigo_ruta')::text, 8, '0')"),
        unique=True,
        nullable=False,
    )
    origen_id = Column(UUID(as_uuid=True), ForeignKey("ubicaciones.id"), nullable=False)
    destino_id = Column(UUID(as_uuid=True), ForeignKey("ubicaciones.id"), nullable=False)
    distancia_km = Column(Numeric(10, 2), nullable=False)
    duracion_horas = Column(Numeric(8, 2), nullable=False)
    geometria = Column(Text, nullable=False)
    paradas = Column(JSONB, nullable=True)
    fuente = Column(String(10), nullable=False, server_default="osrm")
    calculada_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    origen = relationship("Ubicacion", foreign_keys=[origen_id], lazy="joined")
    destino = relationship("Ubicacion", foreign_keys=[destino_id], lazy="joined")

    @property
    def estimada(self) -> bool:
        return self.fuente == "estimada"