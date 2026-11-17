"""/metrics expone las métricas de Prometheus y no exige la clave interna."""
from fastapi.testclient import TestClient

from app.main import app


def test_metrics_expone_contadores_sin_clave_interna(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "clave-de-prueba")
    cliente = TestClient(app)
    cliente.get("/health")
    respuesta = cliente.get("/metrics")
    assert respuesta.status_code == 200 and "http_requests_total" in respuesta.text
    assert cliente.get("/cualquier-ruta").status_code == 403  # el resto del servicio sigue protegido
