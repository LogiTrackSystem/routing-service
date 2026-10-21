import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from . import compartir, flota_client
from .database import SessionLocal
from .models import Ruta, RutaMaestra
from .osrm import SinCarretera
from .trayecto import calcular_tramo_async

INTERVALO_REINTENTO_S = int(os.getenv("REINTENTO_ASIGNACION_S", "30"))
BACKOFF_BASE_S = 30
BACKOFF_MAX_S = 600
LOTE = 50
ESTADOS_FUERA_DE_SAGA = ("historica", "manual")
ESTADOS_EN_VIAJE = ("asignada", "en_curso")
MAX_ANFITRIONES_EVALUADOS = int(os.getenv("MAX_ANFITRIONES_EVALUADOS", "500"))
MAX_INTENTOS_ALCANCE = 3   # cuántos vehículos se prueban si alguno no tiene carretera hasta el origen


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

def _punto(u) -> dict | None:
    if u is None:
        return None
    return {
        "ubicacion_id": str(u.id), "nombre": u.nombre, "latitud": float(u.latitud), "longitud": float(u.longitud),
        "codigo_pais": u.codigo_pais,
    }


def _payload_assigned(ruta: Ruta) -> dict:
    detalle = ruta.detalle_asignacion or {}
    maestra = ruta.ruta_maestra
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
        # Ubicación real y carga compartida (campos nuevos: los consumidores anteriores los ignoran)
        "modo": ruta.modo or "exclusiva",
        "ruta_anfitriona_id": str(ruta.ruta_anfitriona_id) if ruta.ruta_anfitriona_id else None,
        "km_recogida": float(ruta.km_recogida) if ruta.km_recogida is not None else None,
        "km_entrega": float(ruta.km_entrega) if ruta.km_entrega is not None else None,
        "origen": _punto(maestra.origen) if maestra is not None else None,
        "destino": _punto(maestra.destino) if maestra is not None else None,
        "reposicion": ruta.reposicion,
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
        # Si otra tarea la tiene bloqueada, ella misma publicará su evento: no se espera (evita congelar el bucle)
        ruta = db.query(Ruta).filter(Ruta.id == ruta_id).with_for_update(skip_locked=True, of=Ruta).first()
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


def _detalle_de(reserva: dict, **extra) -> dict:
    return {
        "placa": reserva["vehiculo"].get("placa"),
        "tipo": reserva["vehiculo"].get("tipo"),
        "conductor_nombre": reserva["conductor"].get("nombre"),
        "codigo_conductor": reserva["conductor"].get("codigo_conductor"),
        "criterio": (reserva.get("decision") or {}).get("criterio"),
        **extra,
    }


async def _resolver_reposicion(reserva: dict, origen: dict | None) -> dict:
    """Arma el tramo en vacío: desde la última ubicación REAL del vehículo hasta el origen del envío.
    Sin ubicación fiable no se inventa nada: queda registrado el motivo y Tracking decide con su última lectura."""
    info = reserva.get("reposicion") or {}
    desde = info.get("desde")
    base = {
        "desde": desde,
        "hasta": origen,
        "distancia_linea_recta_seleccion_km": info.get("distancia_linea_recta_km"),
        "criterio_seleccion": "linea_recta",
    }
    if origen is None:
        return {**base, "distancia_km": None, "duracion_horas": None, "geometria": None, "fuente": None,
                "motivo": "SIN_ORIGEN_DE_RUTA"}
    if not desde or desde.get("latitud") is None:
        return {**base, "distancia_km": None, "duracion_horas": None, "geometria": None, "fuente": None,
                "motivo": "UBICACION_DESCONOCIDA"}
    if not desde.get("fiable"):
        return {**base, "distancia_km": None, "duracion_horas": None, "geometria": None, "fuente": None,
                "motivo": "UBICACION_NO_FIABLE"}
    tramo = await calcular_tramo_async(desde, origen)   # puede lanzar SinCarretera
    return {**base, **tramo, "motivo": None}


def _eta_exclusiva(maestra, reposicion: dict):
    if maestra is None:
        return None
    horas = float(maestra.duracion_horas) + float((reposicion or {}).get("duracion_horas") or 0.0)
    return _ahora() + timedelta(hours=horas)


# ---------- Carga compartida ----------

def _candidatos_anfitriones(db, ruta: Ruta, maestra, requisitos: dict) -> list:
    """Rutas de vehículos que ya van (o están por ir) por el mismo corredor y a las que el envío podría subirse."""
    hazmat = bool(requisitos.get("es_hazmat"))
    tipo = requisitos.get("tipo_carga") or "general"
    hosts = (
        db.query(Ruta)
        .filter(Ruta.modo == "exclusiva", Ruta.estado.in_(ESTADOS_EN_VIAJE), Ruta.id != ruta.id,
                Ruta.vehiculo_id.isnot(None), Ruta.ruta_maestra_id.isnot(None))
        .order_by(Ruta.creado_en.asc())
        .limit(MAX_ANFITRIONES_EVALUADOS)
        .all()
    )
    candidatos = []
    for host in hosts:
        req = host.requisitos or {}
        if hazmat or req.get("es_hazmat"):
            continue  # HAZMAT viaja solo
        if (req.get("tipo_carga") or "general") != tipo:
            continue  # refrigerada y general no se mezclan
        ev = compartir.evaluar(host, host.ruta_maestra, maestra)
        if ev is not None:
            candidatos.append((host, ev))
    candidatos.sort(key=lambda c: (c[1]["km_recogida"] - c[1]["progreso_km"], c[0].creado_en, str(c[0].id)))
    return candidatos


async def _confirmar_invitada(db, ruta: Ruta, maestra, reserva: dict, host_id, host_fallback_ev) -> bool:
    """Guarda la carga compartida SOLO si el anfitrión sigue en camino (se lee su fila sin esperar: si otro proceso
    la está cerrando, se considera no disponible). Devuelve False sin tocar nada si ya no sirve.
    La lectura del anfitrión ocurre dentro de un SAVEPOINT: si se descarta, se deshace el savepoint y con él el candado
    de esa fila (PostgreSQL lo libera al volver al savepoint); la fila de la propia solicitud sigue bloqueada."""
    savepoint = db.begin_nested()
    try:
        confirmada = _aplicar_invitada(db, ruta, maestra, reserva, host_id)
    except Exception:
        savepoint.rollback()
        raise
    if not confirmada:
        savepoint.rollback()   # suelta el candado del anfitrión descartado
        return False
    db.commit()
    return True


def _aplicar_invitada(db, ruta: Ruta, maestra, reserva: dict, host_id) -> bool:
    host = (
        db.query(Ruta).filter(Ruta.id == host_id)
        .populate_existing().with_for_update(skip_locked=True, of=Ruta).first()
    )
    if host is None or host.estado not in ESTADOS_EN_VIAJE or host.modo != "exclusiva":
        return False
    if str(host.vehiculo_id) != reserva["vehiculo"]["id"]:
        return False
    ev = compartir.evaluar(host, host.ruta_maestra, maestra)  # con el avance real de ESTE momento
    if ev is None:
        return False

    total = float(host.ruta_maestra.distancia_km)
    duracion = float(host.ruta_maestra.duracion_horas)
    despues_de_entrega_h = (total - ev["km_entrega"]) / total * duracion if total else 0.0
    base_eta = host.hora_estimada_llegada or (_ahora() + timedelta(hours=duracion))
    tramo = round(ev["km_entrega"] - ev["km_recogida"], 2)
    ruta.vehiculo_id = uuid.UUID(reserva["vehiculo"]["id"])
    ruta.conductor_id = uuid.UUID(reserva["conductor"]["id"])
    ruta.reserva_id = uuid.UUID(reserva["reserva_id"])
    ruta.detalle_asignacion = _detalle_de(
        reserva, modo="compartida", anfitrion_envio_id=str(host.envio_id),
        recogida=ev["recogida"], entrega=ev["entrega"],
        distancia_fuente="planificada (tramo de la ruta del anfitrión)",
    )
    ruta.modo = "compartida"
    ruta.ruta_anfitriona_id = host.id
    ruta.km_recogida = ev["km_recogida"]
    ruta.km_entrega = ev["km_entrega"]
    ruta.reposicion = None  # no se reposiciona: el vehículo ya va por esa ruta
    ruta.distancia_planificada_km = tramo
    ruta.distancia_km = tramo
    ruta.hora_estimada_llegada = base_eta - timedelta(hours=despues_de_entrega_h)
    ruta.paradas = [
        {"tipo": "origen", "lugar": ev["recogida"], "km_desde_origen": ev["km_recogida"]},
        {"tipo": "destino", "lugar": ev["entrega"], "km_desde_origen": ev["km_entrega"]},
    ]
    ruta.estado = "asignada"
    ruta.ultimo_error = None
    ruta.proximo_reintento_en = None
    ruta.evento_pendiente = "route.assigned"
    return True


async def _intentar_compartir(db, ruta: Ruta, maestra, requisitos: dict) -> bool:
    candidatos = _candidatos_anfitriones(db, ruta, maestra, requisitos)
    for host, ev in candidatos:
        try:
            reserva = await flota_client.reservar_compartida(ruta.envio_id, host.vehiculo_id, requisitos)
        except flota_client.NoCabe:
            continue  # peso, volumen o tipo de carga no caben: se prueba el siguiente
        host_id = host.id
        if reserva["vehiculo"]["id"] != str(host.vehiculo_id):
            # Fleet ya tenía una reserva de ESTE envío en otro vehículo (reintento): se adopta si ese anfitrión sirve
            otro = next((h for h, _ in candidatos if str(h.vehiculo_id) == reserva["vehiculo"]["id"]), None)
            if otro is None:
                await flota_client.liberar(ruta.envio_id)
                continue
            host_id = otro.id
        try:
            if await _confirmar_invitada(db, ruta, maestra, reserva, host_id, ev):
                return True
        except Exception:
            db.rollback()
            try:
                await flota_client.liberar(ruta.envio_id)
            except Exception as exc:
                print(f"[routing] no se pudo compensar la carga compartida del envío {ruta.envio_id}: {exc}")
            raise
        # El anfitrión terminó o ya pasó el punto de recogida mientras tanto: se deshace y se prueba otro
        await flota_client.liberar(ruta.envio_id)
    return False


# ---------- Asignación ----------

async def intentar_asignar(ruta_id) -> str:
    """Intenta asignar vehículo + conductor a una solicitud. Primero intenta subirla a un vehículo que ya va por la
    misma ruta (carga compartida); si no, reserva el vehículo elegible MÁS CERCANO a su origen. Es seguro llamarla
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
        requisitos = ruta.requisitos or {}
        maestra = ruta.ruta_maestra
        origen = _punto(maestra.origen) if maestra is not None else None

        # 1) Compartir primero: subirse a un vehículo que ya va por el mismo corredor
        if compartir.compartir_activo() and maestra is not None:
            try:
                if await _intentar_compartir(db, ruta, maestra, requisitos):
                    await _publicar_pendiente(db, ruta)
                    return "asignada"
            except flota_client.FlotaNoDisponible as exc:
                _marcar_sin_asignacion(db, ruta, f"FLOTA_NO_DISPONIBLE: {exc}")
                await _publicar_pendiente(db, ruta)
                return "sin_asignacion"

        # 2) Vehículo exclusivo: el más cercano que cumpla; si alguno no tiene carretera hasta el origen, se descarta
        excluidos: list = []
        reserva = None
        reposicion = None
        for _ in range(MAX_INTENTOS_ALCANCE):
            try:
                reserva = await flota_client.reservar(envio_id, requisitos, origen, excluidos)
            except flota_client.SinDisponibilidad as exc:
                extra = f" ({len(excluidos)} sin carretera hasta el origen)" if excluidos else ""
                _marcar_sin_asignacion(db, ruta, f"SIN_DISPONIBILIDAD: {exc}{extra}")
                await _publicar_pendiente(db, ruta)
                return "sin_asignacion"
            except flota_client.FlotaNoDisponible as exc:
                _marcar_sin_asignacion(db, ruta, f"FLOTA_NO_DISPONIBLE: {exc}")
                await _publicar_pendiente(db, ruta)
                return "sin_asignacion"

            if reserva.get("modo") == "compartida":
                # Un intento anterior ya dejó la carga en un vehículo en viaje y se cayó antes de guardar: se adopta
                host_id = None
                for host, _ in _candidatos_anfitriones(db, ruta, maestra, requisitos) if maestra is not None else []:
                    if str(host.vehiculo_id) == reserva["vehiculo"]["id"]:
                        host_id = host.id
                        break
                if host_id is not None and await _confirmar_invitada(db, ruta, maestra, reserva, host_id, None):
                    await _publicar_pendiente(db, ruta)
                    return "asignada"
                await flota_client.liberar(envio_id)
                reserva = None
                continue

            try:
                reposicion = await _resolver_reposicion(reserva, origen)
                break
            except SinCarretera:
                # Ese vehículo no tiene carretera hasta el origen: se devuelve intacto y se prueba con otro
                await flota_client.liberar(envio_id, sin_movimiento=True)
                excluidos.append(reserva["vehiculo"]["id"])
                reserva = None
        if reserva is None:
            _marcar_sin_asignacion(
                db, ruta, "SIN_DISPONIBILIDAD: ningún vehículo compatible tiene carretera hasta el origen del envío")
            await _publicar_pendiente(db, ruta)
            return "sin_asignacion"

        # Hay reserva en Fleet: ahora se guarda aquí. Si esto falla, se COMPENSA liberando la reserva.
        try:
            ruta.vehiculo_id = uuid.UUID(reserva["vehiculo"]["id"])
            ruta.conductor_id = uuid.UUID(reserva["conductor"]["id"])
            ruta.reserva_id = uuid.UUID(reserva["reserva_id"])
            ruta.detalle_asignacion = _detalle_de(reserva, modo="exclusiva")
            ruta.modo = "exclusiva"
            ruta.ruta_anfitriona_id = None
            ruta.km_recogida = None
            ruta.km_entrega = None
            ruta.reposicion = reposicion
            if maestra is not None:
                ruta.distancia_planificada_km = maestra.distancia_km   # solo el tramo con carga: es lo que se factura
                ruta.hora_estimada_llegada = _eta_exclusiva(maestra, reposicion)
            ruta.estado = "asignada"
            ruta.ultimo_error = None
            ruta.proximo_reintento_en = None
            ruta.evento_pendiente = "route.assigned"
            db.commit()
        except Exception:
            db.rollback()
            try:
                # route.assigned nunca salió: el vehículo no se movió, conserva su ubicación
                await flota_client.liberar(envio_id, sin_movimiento=True)
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
        # Si route.assigned nunca salió (o nunca hubo vehículo guardado), Tracking no pudo mover el vehículo:
        # se libera "sin movimiento" para que conserve su última ubicación real confiable.
        nunca_salio = bool((ruta.detalle_asignacion or {}).get("sin_vehiculo")) or ruta.evento_pendiente == "route.assigned"
        try:
            await flota_client.liberar(ruta.envio_id, sin_movimiento=nunca_salio)
        except flota_client.FlotaNoDisponible as exc:
            ruta.ultimo_error = f"LIBERACION_PENDIENTE: {exc}"
            db.commit()
            return False
        ruta.estado = "cancelada" if (ruta.detalle_asignacion or {}).get("sin_vehiculo") else "finalizada"
        ruta.ultimo_error = None
        db.commit()
        return True
    finally:
        db.close()


async def _reencolar_invitado(ruta_id) -> bool:
    """El vehículo anfitrión terminó antes de recoger esta carga (devuelto o cancelado): se libera su reserva y el
    envío vuelve a la cola para conseguir otro vehículo. Solo toca cargas que todavía no subieron (estado asignada)."""
    db = SessionLocal()
    try:
        ruta = (
            db.query(Ruta).filter(Ruta.id == ruta_id)
            .with_for_update(skip_locked=True, of=Ruta).first()
        )
        if ruta is None or ruta.modo != "compartida" or ruta.estado != "asignada":
            return False
        try:
            await flota_client.liberar(ruta.envio_id)
        except flota_client.FlotaNoDisponible as exc:
            ruta.ultimo_error = f"REENCOLADO_PENDIENTE: {exc}"
            db.commit()
            return False
        anfitriona = ruta.ruta_anfitriona_id
        motivo = f"ANFITRION_CERRADO: el vehículo (ruta {anfitriona}) terminó antes de recoger la carga"
        maestra = ruta.ruta_maestra
        # Se abre una solicitud NUEVA (otro ruta_id) para que Shipment y Tracking apliquen la nueva asignación como
        # una asignación distinta; la anterior queda como histórica y enlazada.
        nueva = Ruta(
            envio_id=ruta.envio_id, estado="sin_asignacion", ruta_maestra_id=ruta.ruta_maestra_id,
            paradas=_armar_paradas({"origen": maestra.origen.nombre, "destino": maestra.destino.nombre}, maestra)
            if maestra is not None else None,
            distancia_planificada_km=maestra.distancia_km if maestra is not None else None,
            requisitos=ruta.requisitos, intentos=0, ultimo_error=motivo,
        )
        ruta.estado = "historica"
        ruta.proximo_reintento_en = None
        ruta.evento_pendiente = None
        ruta.detalle_asignacion = {**(ruta.detalle_asignacion or {}), "reemplazada": True, "motivo": motivo}
        db.flush()   # la antigua sale del índice de "ruta vigente" antes de insertar la nueva
        db.add(nueva)
        db.commit()
        return True
    finally:
        db.close()


async def _reencolar_invitados_de(ruta_anfitriona_id) -> int:
    db = SessionLocal()
    try:
        ids = [r.id for r in db.query(Ruta.id).filter(
            Ruta.ruta_anfitriona_id == ruta_anfitriona_id, Ruta.modo == "compartida", Ruta.estado == "asignada").all()]
    finally:
        db.close()
    return sum([1 for i in ids if await _reencolar_invitado(i)])


async def procesar_envio_cerrado(payload: dict, motivo: str = "entregado") -> None:
    """El envío terminó (entregado, devuelto o cancelado): se libera la reserva y se reasigna a los que esperan.
    `motivo` queda en la ruta: si un anfitrión no llegó a su destino, las cargas que aún no subieron se reasignan."""
    envio_id = uuid.UUID(payload["envio_id"])
    ruta_id = None
    libera_defensivo = False
    es_anfitriona = False
    for _ in range(15):  # otra tarea puede estar asignando/liberando esta misma ruta: se espera sin congelar el servicio
        db = SessionLocal()
        try:
            ruta = (
                db.query(Ruta)
                .filter(Ruta.envio_id == envio_id, Ruta.estado.not_in(ESTADOS_FUERA_DE_SAGA))
                .with_for_update(skip_locked=True, of=Ruta)
                .first()
            )
            if ruta is None:
                bloqueada = (
                    db.query(Ruta.id).filter(Ruta.envio_id == envio_id, Ruta.estado.not_in(ESTADOS_FUERA_DE_SAGA)).first()
                )
                if bloqueada is None:
                    return
            else:
                if ruta.estado == "sin_asignacion":
                    # Nunca tuvo vehículo guardado, pero Fleet pudo reservar justo antes de una caída: se libera por si acaso
                    ruta.estado = "por_liberar"
                    ruta.proximo_reintento_en = None
                    ruta.evento_pendiente = None
                    ruta.detalle_asignacion = {"cierre": motivo, "sin_vehiculo": True}
                    db.commit()
                    ruta_id, libera_defensivo = ruta.id, True
                    break
                if ruta.estado not in ESTADOS_EN_VIAJE:
                    return
                ruta.detalle_asignacion = {**(ruta.detalle_asignacion or {}), "cierre": motivo}
                ruta.estado = "por_liberar"
                es_anfitriona = ruta.modo == "exclusiva"
                db.commit()
                ruta_id = ruta.id
                break
        finally:
            db.close()
        await asyncio.sleep(1)
    if ruta_id is None:
        print(f"[routing] el envío {envio_id} sigue ocupado; el barrido lo cerrará")
        return

    if not libera_defensivo and es_anfitriona and motivo in ("devuelto", "cancelado"):
        await _reencolar_invitados_de(ruta_id)

    await _liberar_ruta(ruta_id)
    await reintentar_pendientes(forzar=True)


async def procesar_carga_no_recogida(payload: dict) -> None:
    """Tracking avisa que una carga compartida ya no puede subir (el vehículo pasó la recogida o terminó antes). Es el
    mismo criterio en ambos servicios: la carga que no subió vuelve a la cola. Idempotente: solo actúa si sigue asignada."""
    if not payload.get("ruta_id"):
        return
    if await _reencolar_invitado(uuid.UUID(payload["ruta_id"])):
        await reintentar_pendientes(forzar=True)


async def _conciliar_invitados() -> int:
    """Red de seguridad: cargas compartidas cuyo anfitrión ya cerró SIN entregar (por una carrera o una caída)."""
    db = SessionLocal()
    try:
        ids = []
        invitadas = db.query(Ruta).filter(Ruta.modo == "compartida", Ruta.estado == "asignada") \
            .order_by(Ruta.creado_en.asc()).limit(LOTE).all()
        for inv in invitadas:
            host = db.get(Ruta, inv.ruta_anfitriona_id) if inv.ruta_anfitriona_id else None
            cierre = (host.detalle_asignacion or {}).get("cierre") if host is not None else None
            if host is None:
                ids.append(inv.id)
            elif host.estado in ("por_liberar", "finalizada"):
                # "Entregado" a mitad de camino (entrega manual de un operador) tampoco llevó la carga hasta su destino
                prevista = float(host.distancia_planificada_km or 0.0)
                anomalo = cierre == "entregado" and prevista > 0 and float(host.distancia_km or 0.0) < 0.9 * prevista
                if cierre in ("devuelto", "cancelado") or anomalo:
                    ids.append(inv.id)
    finally:
        db.close()
    return sum([1 for i in ids if await _reencolar_invitado(i)])


async def reintentar_pendientes(forzar: bool = False) -> dict:
    """Barrido: libera lo que quedó por liberar, publica eventos pendientes y reintenta
    las solicitudes sin asignación (respetando la espera creciente, salvo forzar=True)."""
    resumen = {"liberadas": 0, "eventos_publicados": 0, "asignadas": 0, "sin_asignacion": 0, "reencoladas": 0}
    resumen["reencoladas"] = await _conciliar_invitados()   # primero, para que las cargas reencoladas entren en este mismo barrido
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