"""Correcciones de la revisión independiente: liberar sin movimiento lo que nunca salió y reasignar la carga que
Tracking avisa que no pudo subir (mismo criterio en ambos servicios)."""
import asyncio
import uuid

from app import asignacion
from app.models import Ruta
from escenarios import payload_envio
from test_carga_compartida import corredor, correr, host, solicitar


def _liberaciones(fleet, envio_id):
    return [c for c in fleet.llamadas if c[0] == "liberar" and c[1] == str(envio_id)]


def test_cerrar_una_solicitud_sin_vehiculo_libera_sin_movimiento(db, fleet, osrm, eventos):
    u, larga, *_ = corredor(db)
    envio = payload_envio(larga, 100)
    correr(asignacion.procesar_shipment_created(envio))      # sin flota: queda sin_asignacion
    correr(asignacion.procesar_envio_cerrado({"envio_id": envio["envio_id"]}, "cancelado"))
    assert _liberaciones(fleet, envio["envio_id"])[0][2] is True


def test_cerrar_un_envio_cuyo_route_assigned_nunca_salio_libera_sin_movimiento(db, fleet, osrm, eventos):
    u, larga, *_ = corredor(db)
    h = host(db, fleet, larga)
    h.evento_pendiente = "route.assigned"       # se cayó RabbitMQ: Tracking nunca supo de este viaje
    db.commit()
    correr(asignacion.procesar_envio_cerrado({"envio_id": str(h.envio_id)}, "cancelado"))
    assert _liberaciones(fleet, h.envio_id)[0][2] is True


def test_cerrar_un_envio_cuyo_viaje_ya_fue_anunciado_libera_con_movimiento(db, fleet, osrm, eventos):
    u, larga, *_ = corredor(db)
    h = host(db, fleet, larga)
    assert h.evento_pendiente is None            # route.assigned ya salió: el vehículo pudo moverse
    correr(asignacion.procesar_envio_cerrado({"envio_id": str(h.envio_id)}, "cancelado"))
    assert _liberaciones(fleet, h.envio_id)[0][2] is False


def test_tracking_avisa_que_la_carga_no_pudo_subir_y_se_reasigna_a_otro_vehiculo(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, peso=300)
    inv = solicitar(db, t2, 100)
    assert inv.modo == "compartida"
    libre = fleet.agregar("LIBRE", 6.24, -75.58)
    h.estado, h.distancia_km = "en_curso", 430      # el vehículo ya pasó por la recogida (km 420) sin que Routing lo supiera
    db.commit()
    correr(asignacion.procesar_carga_no_recogida({"envio_id": str(inv.envio_id), "ruta_id": str(inv.id)}))
    db.expire_all()
    assert db.get(Ruta, inv.id).estado == "historica"
    nueva = db.query(Ruta).filter(Ruta.envio_id == inv.envio_id, Ruta.estado != "historica").one()
    assert nueva.id != inv.id and nueva.modo == "exclusiva" and str(nueva.vehiculo_id) == libre
    assert db.get(Ruta, h.id).estado == "en_curso"          # el anfitrión sigue su camino intacto


def test_el_aviso_de_carga_no_recogida_es_idempotente(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, peso=300)
    inv = solicitar(db, t2, 100)
    fleet.agregar("LIBRE", 6.24, -75.58)
    h.estado, h.distancia_km = "en_curso", 430
    db.commit()
    aviso = {"envio_id": str(inv.envio_id), "ruta_id": str(inv.id)}
    correr(asignacion.procesar_carga_no_recogida(aviso))
    correr(asignacion.procesar_carga_no_recogida(aviso))     # mensaje repetido
    correr(asignacion.procesar_carga_no_recogida({"envio_id": str(uuid.uuid4()), "ruta_id": str(uuid.uuid4())}))
    db.expire_all()
    assert db.query(Ruta).filter(Ruta.envio_id == inv.envio_id, Ruta.estado != "historica").count() == 1
    assert db.query(Ruta).filter(Ruta.envio_id == inv.envio_id).count() == 2
    assert len(_liberaciones(fleet, inv.envio_id)) == 1      # la reserva compartida se liberó una sola vez


def test_el_aviso_no_toca_una_carga_que_ya_va_a_bordo(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    host(db, fleet, larga, peso=300)
    inv = solicitar(db, t2, 100)
    inv.estado = "en_curso"       # ya subió
    db.commit()
    correr(asignacion.procesar_carga_no_recogida({"envio_id": str(inv.envio_id), "ruta_id": str(inv.id)}))
    db.expire_all()
    assert db.get(Ruta, inv.id).estado == "en_curso" and not _liberaciones(fleet, inv.envio_id)
