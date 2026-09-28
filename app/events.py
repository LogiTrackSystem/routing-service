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
SHIPMENT_SERVICE_URL = os.getenv("SHIPMENT_SERVICE_URL")
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
    """Consulta síncrona (REST) a Fleet Service: heurística simple,
    el primer vehículo con estado 'active' (disponible) y capacidad suficiente."""
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


async def _marcar_vehiculo_en_transito(vehiculo_id: str):
    """Cierra el hueco de 'vehiculos.estado nunca cambia': al asignarle una
    ruta, el vehículo deja de estar disponible para nuevas asignaciones
    hasta que Shipment Service lo libere o Maintenance Service lo marque
    en mantenimiento."""
    if not FLEET_SERVICE_URL or not vehiculo_id:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.patch(
                f"{FLEET_SERVICE_URL}/vehiculos/{vehiculo_id}/estado",
                json={"estado": "en_transito"},
            )
    except Exception as exc:
        print(f"[routing] no se pudo marcar el vehículo {vehiculo_id} en_transito: {exc}")


async def _asignar_envio_en_shipment(envio_id: str, vehiculo_id: str, ruta_id: str):
    """Cierra el hueco de 'envio.vehiculo_id/ruta_id nunca se popula':
    le informa a Shipment Service qué vehículo y ruta quedaron asignados,
    usando el endpoint que ya existía pero que nadie llamaba."""
    if not SHIPMENT_SERVICE_URL or not vehiculo_id:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.patch(
                f"{SHIPMENT_SERVICE_URL}/envios/{envio_id}/asignar",
                json={"vehiculo_id": vehiculo_id, "ruta_id": ruta_id},
            )
    except Exception as exc:
        print(f"[routing] no se pudo asignar vehiculo/ruta en Shipment para envío {envio_id}: {exc}")


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

        if vehiculo_id:
            await _marcar_vehiculo_en_transito(vehiculo_id)
            await _asignar_envio_en_shipment(str(envio_id), vehiculo_id, str(ruta.id))

        await publish_event("route.assigned", {
            "ruta_id": str(ruta.id),
            "envio_id": str(envio_id),
            "vehiculo_id": vehiculo_id,
        })
    finally:
        db.close()


async def _procesar_telemetry_raw(payload: dict):
    """Calcula distancia_km REAL de forma progresiva, a partir del odómetro
    real reportado por telemetría, mientras el vehículo está en ruta.
    No toca historial_rutas — eso queda reservado para recálculos manuales
    de paradas (PATCH /rutas/{id}/recalcular)."""
    vehiculo_id = payload.get("vehiculo_id")
    kilometraje = payload.get("kilometraje_acumulado_km")
    if not vehiculo_id or kilometraje is None:
        return

    db: Session = SessionLocal()
    try:
        ruta = (
            db.query(Ruta)
            .filter(Ruta.vehiculo_id == uuid.UUID(vehiculo_id))
            .order_by(Ruta.creado_en.desc())
            .first()
        )
        if ruta is None:
            return

        kilometraje = float(kilometraje)
        if ruta.kilometraje_inicio_ruta is None:
            ruta.kilometraje_inicio_ruta = kilometraje
            ruta.distancia_km = 0
        else:
            distancia = max(0.0, kilometraje - float(ruta.kilometraje_inicio_ruta))
            ruta.distancia_km = round(distancia, 2)
        db.commit()
    finally:
        db.close()


_HANDLERS = {
    "shipment.created": _procesar_shipment_created,
    "telemetry.raw": _procesar_telemetry_raw,
}


async def _on_message(message: aio_pika.IncomingMessage):
    async with message.process():
        payload = json.loads(message.body.decode())
        handler = _HANDLERS.get(message.routing_key)
        if handler:
            await handler(payload)


async def iniciar_consumidor():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue("routing_service.eventos", durable=True)
    await queue.bind(exchange, routing_key="shipment.created")
    await queue.bind(exchange, routing_key="telemetry.raw")
    await queue.consume(_on_message)
    return connection