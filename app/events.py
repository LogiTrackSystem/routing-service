import json
import os
import uuid

import aio_pika
import httpx
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Ruta

RABBITMQ_URL = os.getenv("RABBITMQ_URL")
FLEET_SERVICE_URL = os.getenv("FLEET_SERVICE_URL")
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


async def _sugerir_vehiculo(peso_kg):
    """Consulta síncrona (REST) a Fleet Service, como exige la sección 6 del PDF:
    heurística simple, el primer vehículo activo con capacidad suficiente."""
    if not FLEET_SERVICE_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{FLEET_SERVICE_URL}/vehiculos/")
            resp.raise_for_status()
            vehiculos = resp.json()
    except Exception:
        return None

    for v in vehiculos:
        if v.get("estado") == "active" and float(v.get("capacidad_kg", 0)) >= (peso_kg or 0):
            return v.get("id")
    return None


async def _procesar_shipment_created(payload: dict):
    db: Session = SessionLocal()
    try:
        envio_id = uuid.UUID(payload["envio_id"])
        peso_kg = payload.get("peso_kg")
        vehiculo_id = await _sugerir_vehiculo(peso_kg)

        ruta = Ruta(
            envio_id=envio_id,
            vehiculo_id=uuid.UUID(vehiculo_id) if vehiculo_id else None,
            paradas=[
                {"tipo": "origen", "lugar": payload.get("origen")},
                {"tipo": "destino", "lugar": payload.get("destino")},
            ],
        )
        db.add(ruta)
        db.commit()
        db.refresh(ruta)

        await publish_event("route.assigned", {
            "ruta_id": str(ruta.id),
            "envio_id": str(envio_id),
            "vehiculo_id": vehiculo_id,
        })
    finally:
        db.close()


async def _on_message(message: aio_pika.IncomingMessage):
    async with message.process():
        payload = json.loads(message.body.decode())
        await _procesar_shipment_created(payload)


async def iniciar_consumidor():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue("routing_service.shipment_created", durable=True)
    await queue.bind(exchange, routing_key="shipment.created")
    await queue.consume(_on_message)
    return connection