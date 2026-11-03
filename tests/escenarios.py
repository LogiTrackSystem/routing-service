"""Catálogo mínimo para las pruebas: ciudades, rutas maestras con paradas y envíos."""
import uuid

from app.geo import codificar_polyline
from app.models import Ruta, RutaMaestra, Ubicacion

CIUDADES = {
    "MONTERIA": ("Montería", 8.7480, -75.8814, "CO"),
    "MEDELLIN": ("Medellín", 6.2442, -75.5812, "CO"),
    "BOGOTA": ("Bogotá", 4.7110, -74.0721, "CO"),
    "CALI": ("Cali", 3.4516, -76.5320, "CO"),
    "CARTAGENA": ("Cartagena", 10.3910, -75.4794, "CO"),
    "CARACAS": ("Caracas", 10.4806, -66.9036, "VE"),
}


def ubicaciones(db):
    mapa = {}
    for codigo, (nombre, lat, lon, pais) in CIUDADES.items():
        u = Ubicacion(id=uuid.uuid4(), codigo=codigo[:12], nombre=nombre, nombre_normalizado=nombre.lower(),
                      departamento=nombre, pais="X", codigo_pais=pais, latitud=lat, longitud=lon)
        db.add(u)
        mapa[codigo] = u
    db.commit()
    return mapa


def maestra(db, u, origen, destino, km, horas=None, paradas=None, fuente="osrm"):
    o, d = u[origen], u[destino]
    m = RutaMaestra(
        id=uuid.uuid4(), codigo_ruta=f"RUT-{origen[:3]}{destino[:3]}"[:12], origen_id=o.id, destino_id=d.id,
        distancia_km=km, duracion_horas=horas or round(km / 60, 2),
        geometria=codificar_polyline([(float(o.latitud), float(o.longitud)), (float(d.latitud), float(d.longitud))]),
        paradas=[{"ubicacion_id": str(u[c].id), "codigo": c, "nombre": u[c].nombre, "latitud": float(u[c].latitud),
                  "longitud": float(u[c].longitud), "km_desde_origen": k, "distancia_a_la_via_km": desvio}
                 for c, k, desvio in (paradas or [])],
        fuente=fuente,
    )
    db.add(m)
    db.commit()
    return m


def payload_envio(m, peso=100, **extra):
    return {"envio_id": str(uuid.uuid4()), "ruta_maestra_id": str(m.id), "origen": m.origen.nombre,
            "destino": m.destino.nombre, "peso_kg": peso, **extra}
