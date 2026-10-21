"""Candados reales en PostgreSQL (hilos + transacciones independientes). Se omite sin TEST_PG_URL:
defina TEST_PG_URL=postgresql+psycopg2://usuario:clave@host/base_vacia (nunca guarde esa URL en el repositorio)."""
import asyncio
import os
import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

URL = os.getenv("TEST_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_PG_URL no definida: pruebas de candados en PostgreSQL omitidas")

from app import asignacion, events  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import Ruta  # noqa: E402
from escenarios import maestra, ubicaciones  # noqa: E402


@pytest.fixture()
def pg(monkeypatch):
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(asignacion, "SessionLocal", fabrica)
    monkeypatch.setattr(events, "SessionLocal", fabrica)
    abiertas = []

    def sesion():
        s = fabrica()
        abiertas.append(s)
        return s

    yield sesion
    for s in abiertas:
        s.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _rutas(sesion):
    s = sesion()
    u = ubicaciones(s)
    larga = maestra(s, u, "MONTERIA", "BOGOTA", 800, paradas=[("MEDELLIN", 420, 2.0)])
    tramo = maestra(s, u, "MONTERIA", "MEDELLIN", 420)
    vehiculo = uuid.uuid4()
    anfitrion = Ruta(envio_id=uuid.uuid4(), estado="en_curso", modo="exclusiva", vehiculo_id=vehiculo,
                     ruta_maestra_id=larga.id, distancia_km=500)       # ya pasó la recogida (km 0): no se puede subir
    invitada = Ruta(envio_id=uuid.uuid4(), estado="sin_asignacion", ruta_maestra_id=tramo.id,
                    requisitos={"peso_kg": 100, "tipo_carga": "general"})
    s.add_all([anfitrion, invitada])
    s.commit()
    return anfitrion.id, invitada.id, vehiculo, tramo.id


def _tomar_sin_esperar(sesion, ruta_id):
    """True si otra transacción puede bloquear la fila ya (sin esperar)."""
    s = sesion()
    try:
        s.query(Ruta).filter(Ruta.id == ruta_id).with_for_update(nowait=True).one()
        return True
    except OperationalError:
        return False
    finally:
        s.rollback()
        s.close()


def test_descartar_al_anfitrion_suelta_su_candado_y_conserva_el_de_la_solicitud(pg):
    host_id, inv_id, vehiculo, _ = _rutas(pg)
    s = pg()
    inv = s.query(Ruta).filter(Ruta.id == inv_id).with_for_update(skip_locked=True).one()
    reserva = {"vehiculo": {"id": str(vehiculo)}, "conductor": {"id": str(uuid.uuid4())}, "reserva_id": str(uuid.uuid4())}
    ok = asyncio.run(asignacion._confirmar_invitada(s, inv, inv.ruta_maestra, reserva, host_id, None))
    assert ok is False
    assert _tomar_sin_esperar(pg, host_id) is True        # el anfitrión descartado quedó libre para los demás
    assert _tomar_sin_esperar(pg, inv_id) is False        # la solicitud sigue protegida por quien la está asignando
    s.rollback()


def test_un_aviso_de_viaje_iniciado_no_congela_el_bucle_cuando_la_ruta_esta_ocupada(pg, monkeypatch):
    monkeypatch.setattr(events, "ESPERA_RUTA_OCUPADA_S", 0.05)
    host_id, inv_id, *_ = _rutas(pg)
    s = pg()
    s.query(Ruta).filter(Ruta.id == host_id).with_for_update().one()   # otra tarea tiene la ruta tomada (p. ej. esperando a Fleet)
    latidos = []

    async def principal():
        async def pulso():
            while True:
                latidos.append(time.monotonic())
                await asyncio.sleep(0.02)

        tarea_pulso = asyncio.create_task(pulso())
        aviso = asyncio.create_task(events._procesar_viaje_iniciado({"ruta_id": str(host_id)}))
        await asyncio.sleep(0.5)
        durante = len(latidos)
        pendiente = not aviso.done()
        s.rollback()                       # la otra tarea termina y suelta el candado
        await asyncio.wait_for(aviso, timeout=5)
        tarea_pulso.cancel()
        return durante, pendiente

    durante, pendiente = asyncio.run(principal())
    assert durante >= 10                   # el bucle siguió vivo mientras la ruta estaba ocupada
    assert pendiente is True               # y el aviso esperó sin perderse
    s2 = pg()
    assert s2.query(Ruta).filter(Ruta.id == host_id).one().estado == "en_curso"   # ya estaba en curso: queda igual


def test_la_telemetria_se_descarta_sin_esperar_si_la_ruta_esta_ocupada(pg):
    host_id, inv_id, vehiculo, _ = _rutas(pg)
    s = pg()
    s.query(Ruta).filter(Ruta.id == host_id).with_for_update().one()
    t0 = time.monotonic()
    asyncio.run(events._procesar_telemetry_raw({"vehiculo_id": str(vehiculo), "kilometraje_acumulado_km": 100.0,
                                                "ruta_id": str(host_id), "fase": "viaje"}))
    assert time.monotonic() - t0 < 2       # no esperó el candado
    s.rollback()


def test_publicar_un_evento_pendiente_no_espera_si_otra_tarea_tiene_la_ruta(pg):
    host_id, *_ = _rutas(pg)
    s = pg()
    s.query(Ruta).filter(Ruta.id == host_id).with_for_update().one()
    t0 = time.monotonic()
    assert asyncio.run(asignacion._publicar_por_id(host_id)) is False
    assert time.monotonic() - t0 < 2
    s.rollback()
