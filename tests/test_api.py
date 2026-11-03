import asyncio
import uuid

from fastapi.testclient import TestClient

from app import asignacion
from app.database import get_db
from app.main import app
from escenarios import maestra, payload_envio, ubicaciones


def test_trayecto_devuelve_el_tramo_y_marca_si_es_estimado(osrm):
    c = TestClient(app)
    r = c.get("/trayecto/", params={"desde_lat": 4.3, "desde_lon": -74.8, "hasta_lat": 4.71, "hasta_lon": -74.07})
    assert r.status_code == 200 and r.json()["fuente"] == "osrm" and r.json()["geometria"]
    osrm.caido = True
    r = c.get("/trayecto/", params={"desde_lat": 4.3, "desde_lon": -74.8, "hasta_lat": 4.71, "hasta_lon": -74.07})
    assert r.json()["fuente"] == "estimada"


def test_trayecto_sin_carretera_da_422(osrm):
    osrm.sin_carretera_para = {(4.3, -74.8)}
    r = TestClient(app).get("/trayecto/", params={"desde_lat": 4.3, "desde_lon": -74.8, "hasta_lat": 4.71, "hasta_lon": -74.07})
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "SIN_CARRETERA"


def test_la_ruta_expone_modo_reposicion_sin_geometria_pesada(db, fleet, osrm, eventos):
    u = ubicaciones(db)
    m = maestra(db, u, "BOGOTA", "CALI", 460)
    fleet.agregar("V1", 4.30, -74.80)
    payload = payload_envio(m)
    asyncio.run(asignacion.procesar_shipment_created(payload))
    app.dependency_overrides[get_db] = lambda: db
    try:
        r = TestClient(app).get("/rutas/", params={"envio_id": payload["envio_id"]})
    finally:
        app.dependency_overrides.clear()
    ruta = r.json()[0]
    assert ruta["modo"] == "exclusiva" and ruta["reposicion"]["distancia_km"] > 0
    assert "geometria" not in ruta["reposicion"]
