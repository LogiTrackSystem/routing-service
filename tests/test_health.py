"""/health: lo usan Render y el pipeline de despliegue para comprobar que la versión nueva quedó viva."""
from fastapi.testclient import TestClient

from app.main import app

CLIENTE = TestClient(app)  # sin 'with': no se ejecuta el arranque (RabbitMQ, calentamiento, etc.)


def test_health_devuelve_la_version_de_la_imagen(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "abc1234")
    r = CLIENTE.get("/health")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["status"] == "ok" and cuerpo["service"] == "routing-service" and cuerpo["version"] == "abc1234"


def test_health_sin_version_configurada_indica_dev(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert CLIENTE.get("/health").json()["version"] == "dev"
