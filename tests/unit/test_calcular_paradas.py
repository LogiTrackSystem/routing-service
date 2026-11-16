"""Unitaria 1: geo.calcular_paradas elige las ciudades cercanas a la carretera, sin las pegadas a los extremos."""
from types import SimpleNamespace

from app.geo import calcular_paradas

# carretera recta de sur a norte (unos 222 km)
PUNTOS = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]


def _ciudad(codigo, lat, lon):
    return SimpleNamespace(id=codigo, codigo=codigo, nombre=codigo, latitud=lat, longitud=lon)


def test_calcular_paradas_incluye_la_cercana_y_descarta_lejana_y_extremos():
    candidatas = [_ciudad("MEDIO", 1.0, 0.05), _ciudad("LEJOS", 1.0, 1.0), _ciudad("ORIGEN", 0.01, 0.0)]
    paradas = calcular_paradas(PUNTOS, 222.0, candidatas)
    assert [p["codigo"] for p in paradas] == ["MEDIO"]
    assert 100 < paradas[0]["km_desde_origen"] < 120
