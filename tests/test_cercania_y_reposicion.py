"""Escenarios A y C en Routing: el vehículo sale de DONDE ESTÁ (tramo en vacío) y se elige el más cercano."""
import asyncio
import uuid

from app import asignacion
from app.models import Ruta
from escenarios import maestra, payload_envio, ubicaciones


def correr(c):
    return asyncio.run(c)


def solicitar(db, m, peso=100, **extra):
    payload = payload_envio(m, peso, **extra)
    correr(asignacion.procesar_shipment_created(payload))
    db.expire_all()
    return db.query(Ruta).filter(Ruta.envio_id == uuid.UUID(payload["envio_id"])).one()


def test_elige_el_vehiculo_mas_cercano_al_origen_y_calcula_el_tramo_en_vacio(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    fleet.agregar("LEJOS1", 8.75, -75.88)          # Montería
    cerca = fleet.agregar("CERCA1", 4.30, -74.80)  # Girardot
    r = solicitar(db, m)
    assert r.estado == "asignada" and str(r.vehiculo_id) == cerca
    rep = r.reposicion
    assert rep["fuente"] == "osrm" and rep["motivo"] is None
    assert 100 < rep["distancia_km"] < 150            # Girardot -> Bogotá por carretera (simulada x1.25)
    assert rep["desde"]["latitud"] == 4.30 and rep["hasta"]["nombre"] == "Bogotá"
    # solo el tramo CON carga es lo planificado/facturable; el vacío va aparte
    assert float(r.distancia_planificada_km) == 460


def test_la_hora_estimada_suma_el_tramo_en_vacio_y_el_viaje(db, fleet, osrm, eventos):
    from datetime import datetime, timezone
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 480, horas=8)
    fleet.agregar("V1", 4.30, -74.80)
    antes = datetime.now(timezone.utc)
    r = solicitar(db, m)
    horas = (r.hora_estimada_llegada.replace(tzinfo=timezone.utc) - antes).total_seconds() / 3600
    assert 8 + r.reposicion["duracion_horas"] - 0.05 < horas < 8 + r.reposicion["duracion_horas"] + 0.05


def test_el_evento_route_assigned_lleva_la_reposicion_y_los_puntos(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    fleet.agregar("V1", 4.30, -74.80)
    solicitar(db, m)
    nombre, p = eventos[-1]
    assert nombre == "route.assigned"
    assert p["modo"] == "exclusiva" and p["origen"]["codigo_pais"] == "CO" and p["destino"]["nombre"] == "Cali"
    assert p["reposicion"]["geometria"] and p["reposicion"]["desde"]["fiable"] is True


def test_vehiculo_ya_en_el_origen_no_tiene_tramo(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    fleet.agregar("V1", 4.7115, -74.0725)
    r = solicitar(db, m)
    assert r.reposicion["fuente"] == "mismo_lugar" and r.reposicion["distancia_km"] == 0
    assert osrm.llamadas == 0


def test_sin_ubicacion_conocida_no_se_inventa_una(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    fleet.agregar("SINUBIC")
    r = solicitar(db, m)
    assert r.estado == "asignada"
    assert r.reposicion["motivo"] == "UBICACION_DESCONOCIDA" and r.reposicion["distancia_km"] is None
    assert r.reposicion["desde"] is None and osrm.llamadas == 0


def test_ubicacion_no_fiable_no_se_usa_para_el_tramo(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    fleet.agregar("DUDOSO", 8.75, -75.88, fiable=False)
    r = solicitar(db, m)
    assert r.reposicion["motivo"] == "UBICACION_NO_FIABLE" and r.reposicion["distancia_km"] is None


def test_si_osrm_no_responde_se_estima_y_se_dice(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    fleet.agregar("V1", 4.30, -74.80)
    osrm.caido = True
    r = solicitar(db, m)
    assert r.estado == "asignada"
    assert r.reposicion["fuente"] == "estimada" and r.reposicion["distancia_km"] > 0
    assert r.reposicion["distancia_km"] == round(r.reposicion["linea_recta_km"] * 1.3, 2)


def test_sin_carretera_hasta_el_origen_descarta_ese_vehiculo_y_prueba_otro(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    isla = fleet.agregar("ISLA", 4.30, -74.80)     # el más cercano, pero sin camino
    otro = fleet.agregar("OTRO", 6.24, -75.58)     # Medellín
    osrm.sin_carretera_para = {(4.30, -74.80)}
    r = solicitar(db, m)
    assert r.estado == "asignada" and str(r.vehiculo_id) == otro
    liberaciones = [c for c in fleet.llamadas if c[0] == "liberar"]
    assert liberaciones and liberaciones[0][2] is True          # se devolvió sin movimiento
    reservas = [c for c in fleet.llamadas if c[0] == "reservar"]
    assert isla in reservas[1][3]                                # y se excluyó en el siguiente intento


def test_si_ninguno_tiene_carretera_queda_sin_asignacion_con_motivo(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    fleet.agregar("ISLA", 4.30, -74.80)
    osrm.sin_carretera_para = {(4.30, -74.80)}
    r = solicitar(db, m)
    assert r.estado == "sin_asignacion" and "sin carretera hasta el origen" in r.ultimo_error
    assert not fleet.reservas["%s" % r.envio_id]["activa"]


def test_reintentar_una_ruta_asignada_no_reserva_otra_vez(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    fleet.agregar("V1", 4.30, -74.80)
    fleet.agregar("V2", 4.0, -74.0)
    r = solicitar(db, m)
    vehiculo = r.vehiculo_id
    assert correr(asignacion.intentar_asignar(r.id)) == "ya_asignada"
    db.expire_all()
    assert db.get(Ruta, r.id).vehiculo_id == vehiculo
    assert sum(1 for c in fleet.llamadas if c[0] == "reservar") == 1


def test_sin_ruta_maestra_se_mantiene_el_comportamiento_anterior(db, fleet, osrm, eventos):
    ubicaciones(db)
    fleet.agregar("V1", 4.30, -74.80)
    payload = {"envio_id": str(uuid.uuid4()), "peso_kg": 100}
    correr(asignacion.procesar_shipment_created(payload))
    r = db.query(Ruta).one()
    assert r.estado == "asignada" and r.reposicion["motivo"] == "SIN_ORIGEN_DE_RUTA"
    assert fleet.llamadas[0][2] is None   # no se mandó origen


def test_si_falla_al_guardar_se_compensa_liberando_sin_movimiento(db, fleet, osrm, eventos, monkeypatch):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    fleet.agregar("V1", 4.30, -74.80)
    from app import asignacion as a
    original = a._eta_exclusiva
    monkeypatch.setattr(a, "_eta_exclusiva", lambda *x: (_ for _ in ()).throw(RuntimeError("falla al guardar")))
    payload = payload_envio(m)
    try:
        correr(a.procesar_shipment_created(payload))
    except RuntimeError:
        pass
    monkeypatch.setattr(a, "_eta_exclusiva", original)
    liberaciones = [c for c in fleet.llamadas if c[0] == "liberar"]
    assert liberaciones and liberaciones[-1][2] is True
    assert not fleet.reservas[payload["envio_id"]]["activa"]
