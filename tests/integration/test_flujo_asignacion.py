"""Integración: evento shipment.created -> asignación de vehículo -> ruta consultable por la API."""
import asyncio

from fastapi.testclient import TestClient

from app import asignacion
from app.database import get_db
from app.main import app
from escenarios import maestra, payload_envio, ubicaciones


def test_envio_creado_queda_asignado_y_se_consulta_por_api(db, fleet, osrm, eventos):
    m = maestra(db, ubicaciones(db), "BOGOTA", "CALI", 460)
    fleet.agregar("V1", 4.30, -74.80)
    payload = payload_envio(m)
    asyncio.run(asignacion.procesar_shipment_created(payload))
    app.dependency_overrides[get_db] = lambda: db
    try:
        respuesta = TestClient(app).get("/rutas/", params={"envio_id": payload["envio_id"]})
    finally:
        app.dependency_overrides.clear()
    assert respuesta.status_code == 200 and len(respuesta.json()) == 1
    assert respuesta.json()[0]["modo"] == "exclusiva" and respuesta.json()[0]["vehiculo_id"]
