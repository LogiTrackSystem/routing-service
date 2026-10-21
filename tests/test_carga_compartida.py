"""Escenario B en Routing: un vehículo en ruta recoge otros envíos compatibles que quedan sobre su recorrido."""
import asyncio
import uuid

from app import asignacion, events
from app.models import Ruta
from escenarios import maestra, payload_envio, ubicaciones


def correr(c):
    return asyncio.run(c)


def solicitar(db, m, peso=100, **extra):
    payload = payload_envio(m, peso, **extra)
    correr(asignacion.procesar_shipment_created(payload))
    db.expire_all()
    return db.query(Ruta).filter(Ruta.envio_id == uuid.UUID(payload["envio_id"])).one()


def corredor(db):
    """Montería -> Bogotá (800 km) pasando por Medellín (km 420, a 2 km de la vía)."""
    u = ubicaciones(db)
    larga = maestra(db, u, "MONTERIA", "BOGOTA", 800, paradas=[("MEDELLIN", 420, 2.0)])
    tramo_1 = maestra(db, u, "MONTERIA", "MEDELLIN", 420)
    tramo_2 = maestra(db, u, "MEDELLIN", "BOGOTA", 380)
    contrario = maestra(db, u, "BOGOTA", "MONTERIA", 800)
    return u, larga, tramo_1, tramo_2, contrario


def host(db, fleet, larga, vehiculo="HOST1", capacidad=1000, peso=300, lat=8.75, lon=-75.88):
    fleet.agregar(vehiculo, lat, lon, capacidad=capacidad)
    return solicitar(db, larga, peso)


def test_un_envio_sobre_el_recorrido_se_sube_al_vehiculo_en_ruta(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga)
    otro_libre = fleet.agregar("LIBRE", 8.75, -75.88)  # un vehículo libre idéntico de cerca: aun así se comparte primero
    inv = solicitar(db, t1, 200)
    assert inv.estado == "asignada" and inv.modo == "compartida"
    assert inv.vehiculo_id == h.vehiculo_id and inv.conductor_id == h.conductor_id
    assert inv.ruta_anfitriona_id == h.id
    assert (float(inv.km_recogida), float(inv.km_entrega)) == (0.0, 420.0)
    assert float(inv.distancia_planificada_km) == 420 and inv.reposicion is None
    assert fleet.vehiculos[otro_libre]["ocupado"] == 0 and fleet.vehiculos[str(h.vehiculo_id)]["ocupado"] == 500


def test_la_carga_compartida_publica_los_datos_para_tracking(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga)
    inv = solicitar(db, t2, 100)
    nombre, p = eventos[-1]
    assert nombre == "route.assigned" and p["envio_id"] == str(inv.envio_id)
    assert p["modo"] == "compartida" and p["ruta_anfitriona_id"] == str(h.id)
    assert (p["km_recogida"], p["km_entrega"]) == (420.0, 800.0) and p["reposicion"] is None


def test_la_hora_de_llegada_de_la_carga_compartida_es_antes_que_la_del_anfitrion(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga)
    inv = solicitar(db, t1, 100)
    assert inv.hora_estimada_llegada < h.hora_estimada_llegada


def test_no_se_comparte_si_no_cabe_el_peso_y_sale_otro_vehiculo(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, capacidad=1000, peso=900)
    libre = fleet.agregar("LIBRE", 8.75, -75.88)
    inv = solicitar(db, t1, 200)
    assert inv.modo == "exclusiva" and str(inv.vehiculo_id) == libre and inv.ruta_anfitriona_id is None


def test_no_se_comparte_en_sentido_contrario(db, fleet, osrm, eventos):
    u, larga, t1, t2, contrario = corredor(db)
    host(db, fleet, larga)
    libre = fleet.agregar("LIBRE", 4.71, -74.07)
    inv = solicitar(db, contrario, 100)
    assert inv.modo == "exclusiva" and str(inv.vehiculo_id) == libre


def test_no_se_comparte_si_el_origen_no_esta_sobre_la_ruta(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    host(db, fleet, larga)
    cali_bogota = maestra(db, u, "CALI", "BOGOTA", 460)
    libre = fleet.agregar("LIBRE", 3.45, -76.53)
    inv = solicitar(db, cali_bogota, 100)
    assert inv.modo == "exclusiva" and str(inv.vehiculo_id) == libre


def test_una_parada_demasiado_lejos_de_la_via_no_cuenta_como_sobre_la_ruta(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    lejos = maestra(db, u, "MONTERIA", "BOGOTA", 800, paradas=[("MEDELLIN", 420, 18.0)])  # a 18 km: hay desvío
    t1 = maestra(db, u, "MONTERIA", "MEDELLIN", 420)
    host(db, fleet, lejos)
    libre = fleet.agregar("LIBRE", 8.75, -75.88)
    inv = solicitar(db, t1, 100)
    assert inv.modo == "exclusiva" and str(inv.vehiculo_id) == libre


def test_si_el_vehiculo_ya_paso_por_la_recogida_no_se_comparte(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga)
    h.estado = "en_curso"
    h.distancia_km = 410          # va por el km 410; la recogida en Medellín está en el 420 (< margen de 15 km)
    db.commit()
    libre = fleet.agregar("LIBRE", 6.24, -75.58)
    inv = solicitar(db, t2, 100)
    assert inv.modo == "exclusiva" and str(inv.vehiculo_id) == libre


def test_si_el_vehiculo_aun_no_llega_a_la_recogida_si_se_comparte(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga)
    h.estado = "en_curso"
    h.distancia_km = 300
    db.commit()
    inv = solicitar(db, t2, 100)
    assert inv.modo == "compartida" and float(inv.km_recogida) == 420.0


def test_hazmat_nunca_se_mezcla(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    host(db, fleet, larga)
    libre = fleet.agregar("LIBRE", 8.75, -75.88)
    inv = solicitar(db, t1, 100, es_hazmat=True)
    assert inv.modo == "exclusiva" and str(inv.vehiculo_id) == libre


def test_hazmat_en_marcha_tampoco_acepta_pasajeros(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    fleet.agregar("HAZ", 8.75, -75.88)
    h = solicitar(db, larga, 100, es_hazmat=True)
    libre = fleet.agregar("LIBRE", 8.75, -75.88)
    inv = solicitar(db, t1, 100)
    assert h.modo == "exclusiva" and inv.modo == "exclusiva" and str(inv.vehiculo_id) == libre


def test_refrigerada_no_se_mezcla_con_general_pero_si_con_refrigerada(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    fleet.agregar("FRIO", 8.75, -75.88)
    frio = solicitar(db, larga, 100, tipo_carga="refrigerada")
    libre = fleet.agregar("LIBRE", 8.75, -75.88)
    general = solicitar(db, t1, 100)
    assert general.modo == "exclusiva" and str(general.vehiculo_id) == libre
    otro_frio = solicitar(db, t2, 100, tipo_carga="refrigerada")
    assert otro_frio.modo == "compartida" and otro_frio.ruta_anfitriona_id == frio.id


def test_el_apagado_de_la_carga_compartida_se_respeta(db, fleet, osrm, eventos, monkeypatch):
    monkeypatch.setenv("CARGA_COMPARTIDA_ACTIVA", "false")
    u, larga, t1, t2, _ = corredor(db)
    host(db, fleet, larga)
    libre = fleet.agregar("LIBRE", 8.75, -75.88)
    assert solicitar(db, t1, 100).modo == "exclusiva"


def test_reintentar_la_carga_compartida_no_duplica_la_reserva(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, peso=300)
    inv = solicitar(db, t1, 200)
    assert correr(asignacion.intentar_asignar(inv.id)) == "ya_asignada"
    assert fleet.vehiculos[str(h.vehiculo_id)]["ocupado"] == 500
    assert sum(1 for c in fleet.llamadas if c[0] == "compartida") == 1


def test_un_reintento_tras_caerse_a_mitad_adopta_la_reserva_compartida_existente(db, fleet, osrm, eventos):
    """Fleet ya subió la carga al vehículo pero Routing se cayó antes de guardar: al reintentar no se reserva otro vehículo."""
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, peso=300)
    payload = payload_envio(t1, 200)
    correr(fleet.reservar_compartida(payload["envio_id"], h.vehiculo_id, {"peso_kg": 200}))   # quedó en Fleet
    correr(asignacion.procesar_shipment_created(payload))
    db.expire_all()
    inv = db.query(Ruta).filter(Ruta.envio_id == uuid.UUID(payload["envio_id"])).one()
    assert inv.modo == "compartida" and inv.vehiculo_id == h.vehiculo_id
    assert fleet.vehiculos[str(h.vehiculo_id)]["ocupado"] == 500


def test_varias_cargas_comparten_hasta_llenar_el_vehiculo(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, capacidad=1000, peso=300)
    a = solicitar(db, t1, 300)
    b = solicitar(db, t2, 300)
    c = solicitar(db, t1, 300)       # 1200 > 1000: ya no cabe
    assert (a.modo, b.modo) == ("compartida", "compartida") and c.estado == "sin_asignacion"
    assert fleet.vehiculos[str(h.vehiculo_id)]["ocupado"] == 900


def test_el_anfitrion_devuelto_reencola_las_cargas_que_no_subieron(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, peso=300)
    inv = solicitar(db, t2, 100)     # recogida en Medellín (km 420), aún no sube
    assert inv.modo == "compartida"
    libre = fleet.agregar("LIBRE", 6.24, -75.58)
    correr(asignacion.procesar_envio_cerrado({"envio_id": str(h.envio_id)}, "devuelto"))
    db.expire_all()
    anterior = db.get(Ruta, inv.id)
    assert anterior.estado == "historica" and anterior.detalle_asignacion["reemplazada"] is True
    nueva = db.query(Ruta).filter(Ruta.envio_id == inv.envio_id, Ruta.estado != "historica").one()
    assert nueva.id != inv.id                                                   # solicitud nueva: Shipment/Tracking la aplican de nuevo
    assert nueva.modo == "exclusiva" and nueva.ruta_anfitriona_id is None
    assert nueva.estado == "asignada" and str(nueva.vehiculo_id) == libre       # el barrido forzado ya la reasignó
    assert any(c[0] == "liberar" and c[1] == str(inv.envio_id) for c in fleet.llamadas)


def test_el_anfitrion_entregado_no_toca_a_las_cargas_compartidas(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, peso=300)
    inv = solicitar(db, t2, 100)
    h.distancia_km = 800          # llegó de verdad hasta el final (odómetro): no es una entrega a mitad de camino
    db.commit()
    correr(asignacion.procesar_envio_cerrado({"envio_id": str(h.envio_id)}, "entregado"))
    db.expire_all()
    inv = db.get(Ruta, inv.id)
    assert inv.modo == "compartida" and inv.estado == "asignada"
    assert db.get(Ruta, h.id).estado == "finalizada"
    # el vehículo sigue ocupado por la carga compartida
    assert fleet.vehiculos[str(h.vehiculo_id)]["ocupado"] == 100


def test_entregar_primero_la_carga_compartida_no_libera_al_vehiculo(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, peso=300)
    inv = solicitar(db, t1, 200)
    correr(asignacion.procesar_envio_cerrado({"envio_id": str(inv.envio_id)}, "entregado"))
    db.expire_all()
    assert db.get(Ruta, inv.id).estado == "finalizada"
    assert db.get(Ruta, h.id).estado == "asignada"
    assert fleet.vehiculos[str(h.vehiculo_id)]["ocupado"] == 300


def test_si_la_flota_no_responde_la_carga_queda_en_espera_sin_perder_nada(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    host(db, fleet, larga)
    fleet.caido = True
    inv = solicitar(db, t1, 100)
    assert inv.estado == "sin_asignacion" and "FLOTA_NO_DISPONIBLE" in inv.ultimo_error
    fleet.caido = False
    correr(asignacion.reintentar_pendientes(forzar=True))
    db.expire_all()
    assert db.get(Ruta, inv.id).modo == "compartida"


def test_la_telemetria_solo_mide_la_ruta_del_anfitrion_y_no_cuenta_el_vacio(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    fleet.agregar("V1", 6.24, -75.58)
    h = solicitar(db, larga, 300)          # el vehículo está en Medellín: primero va en vacío a Montería
    inv = solicitar(db, t1, 100)
    assert inv.modo == "compartida"

    def lectura(km, fase, **extra):
        correr(events._procesar_telemetry_raw({"vehiculo_id": str(h.vehiculo_id), "kilometraje_acumulado_km": km,
                                              "ruta_id": str(h.id), "fase": fase, **extra}))
        db.expire_all()

    lectura(1000.0, "reposicion")
    lectura(1100.0, "reposicion")
    assert db.get(Ruta, h.id).kilometraje_inicio_ruta is None and db.get(Ruta, h.id).estado == "asignada"
    lectura(1250.0, "viaje")               # llegó al origen: aquí empieza lo facturable
    lectura(1400.0, "viaje")
    ruta = db.get(Ruta, h.id)
    assert float(ruta.kilometraje_inicio_ruta) == 1250.0 and float(ruta.distancia_km) == 150.0 and ruta.estado == "en_curso"
    assert db.get(Ruta, inv.id).kilometraje_inicio_ruta is None   # la compartida no tiene odómetro propio
    assert float(db.get(Ruta, inv.id).distancia_km) == 420.0      # usa el tramo planificado


def test_viaje_iniciado_de_tracking_marca_en_curso_a_la_carga_compartida(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    host(db, fleet, larga)
    inv = solicitar(db, t2, 100)
    correr(events._procesar_viaje_iniciado({"ruta_id": str(inv.id)}))
    db.expire_all()
    assert db.get(Ruta, inv.id).estado == "en_curso"


def test_cerrar_una_solicitud_sin_vehiculo_la_cancela_y_libera_por_si_acaso(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    envio = payload_envio(larga, 100)
    correr(asignacion.procesar_shipment_created(envio))      # sin flota: queda sin_asignacion
    correr(asignacion.procesar_envio_cerrado({"envio_id": envio["envio_id"]}, "cancelado"))
    db.expire_all()
    r = db.query(Ruta).one()
    assert r.estado == "cancelada"
    assert any(c[0] == "liberar" and c[1] == envio["envio_id"] for c in fleet.llamadas)


def test_entrega_manual_del_anfitrion_a_mitad_de_camino_reencola_la_carga_que_no_subio(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, peso=300)
    inv = solicitar(db, t2, 100)                  # recogida en el km 420: aún no sube
    h.estado, h.distancia_km = "en_curso", 100    # el vehículo iba por el km 100 cuando un operador marcó "entregado"
    db.commit()
    libre = fleet.agregar("LIBRE", 6.24, -75.58)
    correr(asignacion.procesar_envio_cerrado({"envio_id": str(h.envio_id)}, "entregado"))
    db.expire_all()
    assert db.get(Ruta, inv.id).estado == "historica"
    nueva = db.query(Ruta).filter(Ruta.envio_id == inv.envio_id, Ruta.estado != "historica").one()
    assert str(nueva.vehiculo_id) == libre


def test_la_carga_que_ya_va_a_bordo_no_se_reencola_si_el_anfitrion_se_devuelve(db, fleet, osrm, eventos):
    u, larga, t1, t2, _ = corredor(db)
    h = host(db, fleet, larga, peso=300)
    inv = solicitar(db, t1, 100)
    correr(events._procesar_viaje_iniciado({"ruta_id": str(inv.id)}))      # ya subió: Tracking la marcó en curso
    correr(asignacion.procesar_envio_cerrado({"envio_id": str(h.envio_id)}, "devuelto"))
    db.expire_all()
    inv = db.get(Ruta, inv.id)
    assert inv.estado == "en_curso" and inv.modo == "compartida"             # sigue a bordo: la resuelve un operador
