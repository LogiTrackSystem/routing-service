"""Pruebas de Routing con SQLite en memoria y un Fleet simulado (el contrato real se prueba en la integración con PostgreSQL)."""
import itertools
import os
import sys
import uuid

os.environ["DATABASE_URL"] = "sqlite://"
os.environ.pop("INTERNAL_API_KEY", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _jsonb_en_sqlite(tipo, compilador, **kw):
    return "JSON"


from app import asignacion, events, flota_client, trayecto  # noqa: E402
from app.database import Base  # noqa: E402
from app import models  # noqa: E402,F401

for _t in Base.metadata.tables.values():
    for _c in _t.columns:
        if _c.server_default is not None and "nextval" in str(getattr(_c.server_default, "arg", "")):
            _c.server_default = None


@pytest.fixture()
def sesion_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, autoflush=False, expire_on_commit=True)
    monkeypatch.setattr(asignacion, "SessionLocal", fabrica)
    monkeypatch.setattr(events, "SessionLocal", fabrica)
    yield fabrica
    engine.dispose()


@pytest.fixture()
def db(sesion_factory):
    s = sesion_factory()
    yield s
    s.close()


@pytest.fixture()
def eventos(monkeypatch):
    """Captura lo que Routing publicaría en RabbitMQ."""
    publicados = []

    async def falso(nombre, payload):
        publicados.append((nombre, payload))

    monkeypatch.setattr(events, "publish_event", falso)
    return publicados


@pytest.fixture()
def osrm(monkeypatch):
    """OSRM falso: carretera = línea recta x 1.25, 60 km/h. `osrm.caido = True` simula que no responde."""
    from app.geo import codificar_polyline, haversine_km
    from app.osrm import OsrmNoDisponible, SinCarretera

    class Falso:
        caido = False
        sin_carretera_para = set()   # destinos (lat redondeada) sin camino
        llamadas = 0

    estado = Falso()

    def consultar(lon1, lat1, lon2, lat2, intentos=None, timeout=None):
        estado.llamadas += 1
        if estado.caido:
            raise OsrmNoDisponible("caído")
        if (round(lat1, 2), round(lon1, 2)) in estado.sin_carretera_para:
            raise SinCarretera("NoRoute")
        d = haversine_km(lat1, lon1, lat2, lon2) * 1.25
        return {"distancia_km": d, "duracion_horas": d / 60.0, "geometria": codificar_polyline([(lat1, lon1), (lat2, lon2)])}

    monkeypatch.setattr(trayecto, "consultar_osrm", consultar)
    return estado


class FleetFalso:
    """Imita lo esencial de Fleet: reserva idempotente por envío, más cercano primero, carga compartida con peso."""

    def __init__(self):
        self.vehiculos = {}
        self.reservas = {}      # envio_id -> dict
        self.llamadas = []
        self.caido = False
        self._n = itertools.count(1)

    def agregar(self, placa, lat=None, lon=None, pais="CO", capacidad=1000, fiable=True, **extra):
        vid = str(uuid.uuid4())
        self.vehiculos[vid] = dict(id=vid, placa=placa, lat=lat, lon=lon, pais=pais, capacidad=capacidad,
                                   fiable=fiable and lat is not None, ocupado=0, **extra)
        return vid

    def _detalle(self, r, v, ya=False):
        return {
            "reserva_id": r["id"], "envio_id": r["envio"], "estado": "reservada", "modo": r["modo"], "ya_existia": ya,
            "vehiculo": {"id": v["id"], "placa": v["placa"], "tipo": "camion", "capacidad_kg": v["capacidad"]},
            "conductor": {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, v["id"])), "codigo_conductor": 7, "nombre": "Conductor " + v["placa"]},
            "reposicion": {"desde": r["desde"], "distancia_linea_recta_km": r["dist"], "aproximacion": "linea_recta"} if r["modo"] == "exclusiva" else None,
            "decision": {"criterio": r["criterio"]},
        }

    async def reservar(self, envio_id, requisitos, origen=None, excluir=None):
        from app.geo import haversine_km
        self.llamadas.append(("reservar", str(envio_id), origen, list(excluir or [])))
        if self.caido:
            raise flota_client.FlotaNoDisponible("caído")
        previa = self.reservas.get(str(envio_id))
        if previa and previa["activa"]:
            return self._detalle(previa, self.vehiculos[previa["vehiculo"]], ya=True)
        libres = [v for v in self.vehiculos.values()
                  if v["ocupado"] == 0 and v["capacidad"] >= float(requisitos.get("peso_kg") or 0)
                  and v["id"] not in {str(x) for x in (excluir or [])}
                  and not any(r["activa"] and r["vehiculo"] == v["id"] for r in self.reservas.values())]
        if not libres:
            raise flota_client.SinDisponibilidad("No hay un vehículo disponible")

        def clave(v):
            if origen and v["fiable"]:
                return (0, round(haversine_km(v["lat"], v["lon"], origen["latitud"], origen["longitud"]), 1), v["placa"])
            return (1, 0, v["placa"]) if origen else (0, v["capacidad"], v["placa"])

        v = sorted(libres, key=clave)[0]
        dist = round(haversine_km(v["lat"], v["lon"], origen["latitud"], origen["longitud"]), 2) if origen and v["lat"] is not None else None
        desde = None if v["lat"] is None else {
            "latitud": v["lat"], "longitud": v["lon"], "codigo_pais": v["pais"], "nombre": None,
            "tomada_en": "2026-10-20T10:00:00+00:00", "fuente": "entrega", "fiable": v["fiable"]}
        r = dict(id=str(uuid.uuid4()), envio=str(envio_id), vehiculo=v["id"], modo="exclusiva", activa=True,
                 desde=desde, dist=dist, criterio="cercania_linea_recta" if origen else "capacidad", peso=float(requisitos.get("peso_kg") or 0))
        v["ocupado"] = r["peso"]
        self.reservas[str(envio_id)] = r
        return self._detalle(r, v)

    async def reservar_compartida(self, envio_id, vehiculo_id, requisitos):
        self.llamadas.append(("compartida", str(envio_id), str(vehiculo_id)))
        if self.caido:
            raise flota_client.FlotaNoDisponible("caído")
        previa = self.reservas.get(str(envio_id))
        if previa and previa["activa"]:
            return self._detalle(previa, self.vehiculos[previa["vehiculo"]], ya=True)
        v = self.vehiculos.get(str(vehiculo_id))
        if v is None:
            raise flota_client.NoCabe("VEHICULO_NO_ENCONTRADO", "no existe")
        if not any(r["activa"] and r["vehiculo"] == v["id"] for r in self.reservas.values()):
            raise flota_client.NoCabe("VEHICULO_NO_ACEPTA_CARGA", "sin viaje")
        peso = float(requisitos.get("peso_kg") or 0)
        if v["ocupado"] + peso > v["capacidad"]:
            raise flota_client.NoCabe("CAPACIDAD_EXCEDIDA", "no cabe")
        v["ocupado"] += peso
        r = dict(id=str(uuid.uuid4()), envio=str(envio_id), vehiculo=v["id"], modo="compartida", activa=True,
                 desde=None, dist=None, criterio="carga_compartida", peso=peso)
        self.reservas[str(envio_id)] = r
        return self._detalle(r, v)

    async def liberar(self, envio_id, sin_movimiento=False):
        self.llamadas.append(("liberar", str(envio_id), sin_movimiento))
        if self.caido:
            raise flota_client.FlotaNoDisponible("caído")
        r = self.reservas.get(str(envio_id))
        if r and r["activa"]:
            r["activa"] = False
            v = self.vehiculos[r["vehiculo"]]
            v["ocupado"] = max(0.0, v["ocupado"] - r["peso"])
            if not any(x["activa"] and x["vehiculo"] == v["id"] for x in self.reservas.values()):
                v["ocupado"] = 0
        return {"envio_id": str(envio_id), "liberado": bool(r)}


@pytest.fixture()
def fleet(monkeypatch):
    f = FleetFalso()
    monkeypatch.setattr(flota_client, "reservar", f.reservar)
    monkeypatch.setattr(flota_client, "reservar_compartida", f.reservar_compartida)
    monkeypatch.setattr(flota_client, "liberar", f.liberar)
    return f
