import json
import os
import uuid

import aio_pika
from sqlalchemy.orm import Session

from .asignacion import procesar_envio_cerrado, procesar_shipment_created
from .database import SessionLocal
from .models import Ruta

RABBITMQ_URL = os.getenv("RABBITMQ_URL")
EXCHANGE_NAME = "logitrack_events"


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
    """Calcula distancia_km REAL de forma progresiva, a partir del odómetro
    reportado por telemetría, solo para la ruta vigente del vehículo.
    No toca historial_rutas — eso queda reservado para recálculos manuales."""
    vehiculo_id = payload.get("vehiculo_id")
    kilometraje = payload.get("kilometraje_acumulado_km")
    if not vehiculo_id or kilometraje is None:
        return

    db: Session = SessionLocal()
    try:
        ruta = (
            db.query(Ruta)
            .filter(
                Ruta.vehiculo_id == uuid.UUID(vehiculo_id),
                Ruta.estado.in_(("asignada", "en_curso")),
            )
            .order_by(Ruta.creado_en.desc())
            .first()
        )
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


async def _procesar_shipment_cerrado(payload: dict):
    await procesar_envio_cerrado(payload)


_HANDLERS = {
    "shipment.created": procesar_shipment_created,
    "shipment.delivered": _procesar_shipment_cerrado,
    "shipment.returned": _procesar_shipment_cerrado,
    "shipment.cancelled": _procesar_shipment_cerrado,  # cancelado antes de salir: se libera o se abandona la solicitud
    "telemetry.raw": _procesar_telemetry_raw,
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
    for clave in ("shipment.created", "shipment.delivered", "shipment.returned", "shipment.cancelled", "telemetry.raw"):
        await queue.bind(exchange, routing_key=clave)
    await queue.consume(_on_message)
    return connection