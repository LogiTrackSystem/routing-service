import asyncio
import json
import os
import uuid

import aio_pika
from sqlalchemy.orm import Session

from .asignacion import procesar_carga_no_recogida, procesar_envio_cerrado, procesar_shipment_created
from .database import SessionLocal
from .models import Ruta

RABBITMQ_URL = os.getenv("RABBITMQ_URL")
EXCHANGE_NAME = "logitrack_events"
ESPERA_RUTA_OCUPADA_S = float(os.getenv("ESPERA_RUTA_OCUPADA_S", "0.5"))
INTENTOS_RUTA_OCUPADA = int(os.getenv("INTENTOS_RUTA_OCUPADA", "120"))


async def publish_event(routing_key: str, payload: dict):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        message = aio_pika.Message(
            body=json.dumps(payload, default=str).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key=routing_key)


async def _procesar_telemetry_raw(payload: dict):
    """Calcula distancia_km REAL de forma progresiva, a partir del odómetro reportado por telemetría, solo para la
    ruta vigente del vehículo. El tramo en vacío hacia el origen (fase "reposicion") NO cuenta: Billing factura solo
    el recorrido con carga. Las cargas compartidas no tienen odómetro propio (usan el tramo planificado del anfitrión).
    No toca historial_rutas — eso queda reservado para recálculos manuales."""
    vehiculo_id = payload.get("vehiculo_id")
    kilometraje = payload.get("kilometraje_acumulado_km")
    if not vehiculo_id or kilometraje is None:
        return
    if payload.get("fase") == "reposicion":
        return

    db: Session = SessionLocal()
    try:
        consulta = db.query(Ruta).filter(
            Ruta.vehiculo_id == uuid.UUID(vehiculo_id),
            Ruta.estado.in_(("asignada", "en_curso")),
            Ruta.modo == "exclusiva",
        )
        if payload.get("ruta_id"):
            consulta = consulta.filter(Ruta.id == uuid.UUID(payload["ruta_id"]))
        # Sin esperar: si otra tarea tiene la ruta bloqueada (esperando a Fleet o a RabbitMQ) una espera síncrona
        # congelaría todo el bucle de eventos. Esta lectura se descarta; el odómetro es acumulado y la siguiente la cubre.
        ruta = consulta.order_by(Ruta.creado_en.desc()).with_for_update(skip_locked=True, of=Ruta).first()
        if ruta is None:
            return

        kilometraje = float(kilometraje)
        if ruta.kilometraje_inicio_ruta is None:
            ruta.kilometraje_inicio_ruta = kilometraje
            ruta.distancia_km = 0
            ruta.estado = "en_curso"
        else:
            distancia = max(0.0, kilometraje - float(ruta.kilometraje_inicio_ruta))
            ruta.distancia_km = round(distancia, 2)
        db.commit()
    finally:
        db.close()


async def _procesar_viaje_iniciado(payload: dict):
    """Tracking avisa que el viaje con carga arrancó (también para cargas compartidas, que no tienen telemetría propia).
    Este aviso llega una sola vez, así que si la ruta está ocupada se reintenta SIN bloquear el bucle de eventos."""
    if not payload.get("ruta_id"):
        return
    ruta_id = uuid.UUID(payload["ruta_id"])
    for _ in range(INTENTOS_RUTA_OCUPADA):
        db: Session = SessionLocal()
        try:
            ruta = db.query(Ruta).filter(Ruta.id == ruta_id).with_for_update(skip_locked=True, of=Ruta).first()
            if ruta is not None:
                if ruta.estado == "asignada":
                    ruta.estado = "en_curso"
                    db.commit()
                return
            if db.query(Ruta.id).filter(Ruta.id == ruta_id).first() is None:
                return  # esa ruta no existe
        finally:
            db.close()
        await asyncio.sleep(ESPERA_RUTA_OCUPADA_S)   # existe pero otra tarea la tiene tomada: se espera sin bloquear
    raise RuntimeError(f"la ruta {ruta_id} sigue ocupada; no se aplicó tracking.trip_started")


def _cerrado(motivo: str):
    async def manejador(payload: dict):
        await procesar_envio_cerrado(payload, motivo)
    return manejador


_HANDLERS = {
    "shipment.created": procesar_shipment_created,
    "shipment.delivered": _cerrado("entregado"),
    "shipment.returned": _cerrado("devuelto"),
    "shipment.cancelled": _cerrado("cancelado"),  # cancelado antes de salir: se libera o se abandona la solicitud
    "telemetry.raw": _procesar_telemetry_raw,
    "tracking.trip_started": _procesar_viaje_iniciado,
    "tracking.shared_load_missed": procesar_carga_no_recogida,   # el vehículo ya pasó la recogida: se reasigna la carga
}


async def _on_message(message: aio_pika.IncomingMessage):
    async with message.process():
        payload = json.loads(message.body.decode())
        handler = _HANDLERS.get(message.routing_key)
        if handler:
            try:
                await handler(payload)
            except Exception as exc:
                print(f"[routing] error procesando {message.routing_key}: {exc}")


async def iniciar_consumidor():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue("routing_service.eventos", durable=True)
    for clave in _HANDLERS:
        await queue.bind(exchange, routing_key=clave)
    await queue.consume(_on_message)
    return connection