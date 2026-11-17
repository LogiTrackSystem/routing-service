"""Unitaria 2: asignacion.procesar_shipment_created crea la solicitud de ruta y le asigna un vehículo."""
import asyncio
import uuid

from app import asignacion
from app.models import Ruta
from escenarios import maestra, payload_envio, ubicaciones


def test_envio_creado_genera_una_sola_ruta_con_vehiculo_aunque_el_evento_se_repita(db, fleet, osrm, eventos):
    # Arrange: catálogo, una ruta maestra y un vehículo libre (Fleet y OSRM simulados)
    m = maestra(db, ubicaciones(db), "BOGOTA", "CALI", 460)
    fleet.agregar("V1", 4.30, -74.80)
    payload = payload_envio(m)
    # Act: el mismo evento llega dos veces
    asyncio.run(asignacion.procesar_shipment_created(payload))
    asyncio.run(asignacion.procesar_shipment_created(payload))
    db.expire_all()
    # Assert
    ruta = db.query(Ruta).filter(Ruta.envio_id == uuid.UUID(payload["envio_id"])).one()
    assert ruta.vehiculo_id is not None
    assert any(nombre == "route.assigned" for nombre, _ in eventos)
