"""Clave interna entre el gateway y los servicios (opcional).

Si la variable INTERNAL_API_KEY está definida, este servicio solo atiende peticiones que traigan la
cabecera X-Internal-Key con ese mismo valor (las envían el gateway y los demás servicios). Así, aunque
el servicio tenga una URL pública, nadie puede saltarse el gateway (login y roles) llamándolo directo.
/health queda abierto para los chequeos de la plataforma.

Si INTERNAL_API_KEY no está definida no hace nada: desarrollo local y pruebas siguen igual.
Debe tener el MISMO valor en el gateway y en todos los servicios.
"""
import hmac
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

CABECERA = "X-Internal-Key"
RUTAS_ABIERTAS = ("/health",)


def clave_interna() -> str:
    return os.getenv("INTERNAL_API_KEY", "").strip()


def cabeceras_internas() -> dict:
    """Cabecera que se agrega a las llamadas HTTP hacia otros servicios (vacía si no hay clave)."""
    clave = clave_interna()
    return {CABECERA: clave} if clave else {}


def proteger_servicio(app: FastAPI) -> None:
    @app.middleware("http")
    async def _exigir_clave_interna(request, call_next):
        clave = clave_interna()
        if clave and request.method != "OPTIONS" and request.url.path not in RUTAS_ABIERTAS:
            recibida = request.headers.get(CABECERA, "")
            if not hmac.compare_digest(recibida.encode("utf-8"), clave.encode("utf-8")):
                return JSONResponse(
                    status_code=403,
                    content={"detail": {
                        "codigo": "ACCESO_DIRECTO_NO_PERMITIDO",
                        "mensaje": "Este servicio solo atiende peticiones que llegan por el API Gateway",
                    }},
                )
        return await call_next(request)
