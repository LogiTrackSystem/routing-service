import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .interno import proteger_servicio

from .asignacion import bucle_reintentos
from .database import SessionLocal
from .routers import asignaciones, rutas, rutas_maestras, ubicaciones
from .events import iniciar_consumidor
from .seed_ubicaciones import sembrar_ubicaciones


def _sembrar_catalogo():
    db = SessionLocal()
    try:
        nuevas = sembrar_ubicaciones(db)
        if nuevas:
            print(f"[routing] catalogo de ubicaciones: {nuevas} sembradas")
    except Exception as exc:
        db.rollback()
        print(f"[routing] no se pudo sembrar el catalogo de ubicaciones: {exc}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _sembrar_catalogo()
    connection = await iniciar_consumidor()
    tarea_reintentos = asyncio.create_task(bucle_reintentos())
    yield
    tarea_reintentos.cancel()
    await connection.close()


app = FastAPI(title="Routing Service", lifespan=lifespan)
app.include_router(rutas.router)
proteger_servicio(app)
app.include_router(ubicaciones.router)
app.include_router(rutas_maestras.router)
app.include_router(asignaciones.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "routing-service"}