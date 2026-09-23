from contextlib import asynccontextmanager
from fastapi import FastAPI

from .routers import rutas
from .events import iniciar_consumidor


@asynccontextmanager
async def lifespan(app: FastAPI):
    connection = await iniciar_consumidor()
    yield
    await connection.close()


app = FastAPI(title="Routing Service", lifespan=lifespan)
app.include_router(rutas.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "routing-service"}