import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from . import flota_client
from .database import SessionLocal
from .models import Ruta, RutaMaestra

INTERVALO_REINTENTO_S = int(os.getenv("REINTENTO_ASIGNACION_S", "30"))
BACKOFF_BASE_S = 30
BACKOFF_MAX_S = 600
LOTE = 50
ESTADOS_FUERA_DE_SAGA = ("historica", "manual")


def _ahora():
    return datetime.now(timezone.utc)


def _ruta_vigente(db, envio_id):
    return (
        db.query(Ruta)
        .filter(Ruta.envio_id == envio_id, Ruta.estado.not_in(ESTADOS_FUERA_DE_SAGA))
        .first()
    )


def _backoff(intentos: int) -> int:
    return min(BACKOFF_BASE_S * 2 ** max(intentos - 1, 0), BACKOFF_MAX_S)


def _armar_paradas(payload: dict, maestra):
    paradas = [{"tipo": "origen", "lugar": payload.get("origen")}]
    if maestra is not None and maestra.paradas:
        for p in maestra.paradas:
            paradas.append({
                "tipo": "parada",
                "lugar": p.get("nombre"),
                "km_desde_origen": p.get("km_desde_origen"),
                "latitud": p.get("latitud"),
                "longitud": p.get("longitud"),
            })
    paradas.append({"tipo": "destino", "lugar": payload.get("destino")})
    return paradas


# ---------- Eventos de salida (con reintento de publicación) ----------

def _payload_assigned(ruta: Ruta) -> dict:
    detalle = ruta.detalle_asignacion or {}
    return {
        "ruta_id": str(ruta.id),
        "envio_id": str(ruta.envio_id),
        "vehiculo_id": str(ruta.vehiculo_id),
        "conductor_id": str(ruta.conductor_id),
        "placa": detalle.get("placa"),
        "tipo_vehiculo": detalle.get("tipo"),
        "conductor_nombre": detalle.get("conductor_nombre"),
        "codigo_conductor": detalle.get("codigo_conductor"),
        "ruta_maestra_id": str(ruta.ruta_maestra_id) if ruta.ruta_maestra_id else None,
        "codigo_ruta": ruta.codigo_ruta,
        "distancia_km": float(ruta.distancia_planificada_km) if ruta.distancia_planificada_km is not None else None,
        "hora_estimada_llegada": ruta.hora_estimada_llegada,
    }


def _payload_unassigned(ruta: Ruta) -> dict:
    return {
        "ruta_id": str(ruta.id),
        "envio_id": str(ruta.envio_id),
        "motivo": ruta.ultimo_error,
        "intentos": ruta.intentos,
    }


async def _publicar_pendiente(db, ruta: Ruta) -> bool:
    from .events import publish_event  # import local: events.py importa este módulo

    if not ruta.evento_pendiente:
        return True
    nombre = ruta.evento_pendiente
    payload = _payload_assigned(ruta) if nombre == "route.assigned" else _payload_unassigned(ruta)
    try:
        await publish_event(nombre, payload)
    except Exception as exc:
        print(f"[routing] no se pudo publicar {nombre} del envío {ruta.envio_id} (se reintentará): {exc}")
        return False
    ruta.evento_pendiente = None
    db.commit()
    return True


async def _publicar_por_id(ruta_id) -> bool:
    db = SessionLocal()
    try:
        ruta = db.query(Ruta).filter(Ruta.id == ruta_id).first()
        if ruta is None:
            return False
        return await _publicar_pendiente(db, ruta)
    finally:
        db.close()


# ---------- Pasos de la Saga ----------

def _marcar_sin_asignacion(db, ruta: Ruta, motivo: str) -> None:
    motivo_anterior = ruta.ultimo_error
    ruta.estado = "sin_asignacion"
    ruta.intentos = (ruta.intentos or 0) + 1
    ruta.ultimo_error = motivo
    ruta.proximo_reintento_en = _ahora() + timedelta(seconds=_backoff(ruta.intentos))
    if ruta.intentos == 1 or motivo != motivo_anterior:
        ruta.evento_pendiente = "route.unassigned"  # solo se avisa al empezar o si cambia el motivo
    db.commit()


async def intentar_asignar(ruta_id) -> str:
    """Intenta reservar vehículo + conductor para una solicitud. Es seguro llamarla
    varias veces para la misma ruta (idempotente). Devuelve el resultado como texto."""
    db = SessionLocal()
    try:
        ruta = (
            db.query(Ruta)
            .filter(Ruta.id == ruta_id)
            .with_for_update(skip_locked=True, of=Ruta)
            .first()
        )
        if ruta is None:
            return "ocupada"  # otro proceso la está trabajando ahora mismo
        if ruta.estado == "asignada":
            await _publicar_pendiente(db, ruta)
            return "ya_asignada"
        if ruta.estado != "sin_asignacion":
            return ruta.estado

        envio_id = ruta.envio_id
        try:
            reserva = await flota_client.reservar(envio_id, ruta.requisitos or {})
        except flota_client.SinDisponibilidad as exc:
            _marcar_sin_asignacion(db, ruta, f"SIN_DISPONIBILIDAD: {exc}")
            await _publicar_pendiente(db, ruta)
            return "sin_asignacion"
        except flota_client.FlotaNoDisponible as exc:
            _marcar_sin_asignacion(db, ruta, f"FLOTA_NO_DISPONIBLE: {exc}")
            await _publicar_pendiente(db, ruta)
            return "sin_asignacion"

        # Hay reserva en Fleet: ahora se guarda aquí. Si esto falla, se COMPENSA liberando la reserva.
        try:
            maestra = ruta.ruta_maestra
            ruta.vehiculo_id = uuid.UUID(reserva["vehiculo"]["id"])
            ruta.conductor_id = uuid.UUID(reserva["conductor"]["id"])
            ruta.reserva_id = uuid.UUID(reserva["reserva_id"])
            ruta.detalle_asignacion = {
                "placa": reserva["vehiculo"].get("placa"),
                "tipo": reserva["vehiculo"].get("tipo"),
                "conductor_nombre": reserva["conductor"].get("nombre"),
                "codigo_conductor": reserva["conductor"].get("codigo_conductor"),
            }
            if maestra is not None:
                ruta.distancia_planificada_km = maestra.distancia_km
                ruta.hora_estimada_llegada = _ahora() + timedelta(hours=float(maestra.duracion_horas))
            ruta.estado = "asignada"
            ruta.ultimo_error = None
            ruta.proximo_reintento_en = None
            ruta.evento_pendiente = "route.assigned"
            db.commit()
        except Exception:
            db.rollback()
            try:
                await flota_client.liberar(envio_id)
            except Exception as exc:
                print(f"[routing] no se pudo compensar la reserva del envío {envio_id}: {exc}")
            raise

        await _publicar_pendiente(db, ruta)
        return "asignada"
    finally:
        db.close()


async def procesar_shipment_created(payload: dict) -> None:
    envio_id = uuid.UUID(payload["envio_id"])
    maestra_id = payload.get("ruta_maestra_id")

    db = SessionLocal()
    try:
        ruta = _ruta_vigente(db, envio_id)  # idempotencia: un mensaje repetido no duplica la solicitud
        if ruta is None:
            maestra = db.get(RutaMaestra, uuid.UUID(maestra_id)) if maestra_id else None
            ruta = Ruta(
                envio_id=envio_id,
                estado="sin_asignacion",
                ruta_maestra_id=maestra.id if maestra else None,
                paradas=_armar_paradas(payload, maestra),
                distancia_planificada_km=maestra.distancia_km if maestra else None,
                requisitos={
                    "peso_kg": payload.get("peso_kg"),
                    "volumen_m3": payload.get("volumen_m3"),
                    "tipo_carga": payload.get("tipo_carga") or "general",
                    "es_hazmat": bool(payload.get("es_hazmat")),
                },
            )
            db.add(ruta)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                ruta = _ruta_vigente(db, envio_id)
        ruta_id = ruta.id if ruta is not None else None
    finally:
        db.close()

    if ruta_id is not None:
        await intentar_asignar(ruta_id)


async def _liberar_ruta(ruta_id) -> bool:
    db = SessionLocal()
    try:
        ruta = (
            db.query(Ruta)
            .filter(Ruta.id == ruta_id)
            .with_for_update(skip_locked=True, of=Ruta)
            .first()
        )
        if ruta is None or ruta.estado != "por_liberar":
            return False
        try:
            await flota_client.liberar(ruta.envio_id)
        except flota_client.FlotaNoDisponible as exc:
            ruta.ultimo_error = f"LIBERACION_PENDIENTE: {exc}"
            db.commit()
            return False
        ruta.estado = "finalizada"
        ruta.ultimo_error = None
        db.commit()
        return True
    finally:
        db.close()


async def procesar_envio_cerrado(payload: dict) -> None:
    """El envío terminó (entregado o devuelto): se libera la reserva y se reasigna a los que esperan."""
    envio_id = uuid.UUID(payload["envio_id"])
    db = SessionLocal()
    try:
        ruta = (
            db.query(Ruta)
            .filter(Ruta.envio_id == envio_id, Ruta.estado.not_in(ESTADOS_FUERA_DE_SAGA))
            .with_for_update(of=Ruta)
            .first()
        )
        if ruta is None:
            return
        if ruta.estado == "sin_asignacion":
            ruta.estado = "cancelada"  # nunca tuvo vehículo: se deja de reintentar
            ruta.proximo_reintento_en = None
            ruta.evento_pendiente = None
            db.commit()
            return
        if ruta.estado not in ("asignada", "en_curso"):
            return
        ruta.estado = "por_liberar"
        db.commit()
        ruta_id = ruta.id
    finally:
        db.close()

    await _liberar_ruta(ruta_id)
    await reintentar_pendientes(forzar=True)


async def reintentar_pendientes(forzar: bool = False) -> dict:
    """Barrido: libera lo que quedó por liberar, publica eventos pendientes y reintenta
    las solicitudes sin asignación (respetando la espera creciente, salvo forzar=True)."""
    resumen = {"liberadas": 0, "eventos_publicados": 0, "asignadas": 0, "sin_asignacion": 0}
    db = SessionLocal()
    try:
        por_liberar = [r.id for r in db.query(Ruta).filter(Ruta.estado == "por_liberar").limit(LOTE).all()]
        con_evento = [
            r.id for r in db.query(Ruta)
            .filter(Ruta.evento_pendiente.isnot(None))
            .order_by(Ruta.actualizado_en.asc()).limit(LOTE).all()
        ]
        consulta = db.query(Ruta).filter(Ruta.estado == "sin_asignacion", Ruta.requisitos.isnot(None))
        if not forzar:
            consulta = consulta.filter(
                or_(Ruta.proximo_reintento_en.is_(None), Ruta.proximo_reintento_en <= _ahora())
            )
        sin_asignar = [r.id for r in consulta.order_by(Ruta.creado_en.asc()).limit(LOTE).all()]
    finally:
        db.close()

    for ruta_id in por_liberar:
        if await _liberar_ruta(ruta_id):
            resumen["liberadas"] += 1
    for ruta_id in con_evento:
        if await _publicar_por_id(ruta_id):
            resumen["eventos_publicados"] += 1
    for ruta_id in sin_asignar:  # los más antiguos primero
        resultado = await intentar_asignar(ruta_id)
        if resultado in ("asignada", "ya_asignada"):
            resumen["asignadas"] += 1
        elif resultado == "sin_asignacion":
            resumen["sin_asignacion"] += 1
    return resumen


async def bucle_reintentos() -> None:
    while True:
        await asyncio.sleep(INTERVALO_REINTENTO_S)
        try:
            await reintentar_pendientes()
        except Exception as exc:
            print(f"[routing] error en el ciclo de reintentos: {exc}")