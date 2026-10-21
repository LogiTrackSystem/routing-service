import asyncio
import os

import httpx
from .interno import cabeceras_internas
from dotenv import load_dotenv

load_dotenv()

FLEET_SERVICE_URL = os.getenv("FLEET_SERVICE_URL")
TIMEOUT_S = 10.0
INTENTOS = 3


class SinDisponibilidad(Exception):
    """Fleet respondió que no hay un vehículo con conductor compatible disponible."""


class NoCabe(Exception):
    """Fleet rechazó sumar la carga a un vehículo en viaje (capacidad, tipo de carga, vehículo ya libre...)."""

    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


class FlotaNoDisponible(Exception):
    """No se pudo hablar con Fleet (caído, tiempo agotado, error del servidor)."""


async def _post(ruta: str, cuerpo: dict) -> httpx.Response:
    if not FLEET_SERVICE_URL:
        raise FlotaNoDisponible("FLEET_SERVICE_URL no está configurada")
    ultimo_error = "sin intentos"
    for intento in range(1, INTENTOS + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S, headers=cabeceras_internas()) as client:
                resp = await client.post(f"{FLEET_SERVICE_URL}{ruta}", json=cuerpo)
        except httpx.HTTPError as exc:
            ultimo_error = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code < 500:
                return resp
            ultimo_error = f"Fleet respondió HTTP {resp.status_code}"
        if intento < INTENTOS:
            await asyncio.sleep(intento)  # espera 1 s y luego 2 s
    raise FlotaNoDisponible(ultimo_error)


async def reservar(envio_id, requisitos: dict, origen: dict | None = None, excluir: list | None = None) -> dict:
    """Pide a Fleet la reserva atómica de vehículo + conductor. Es idempotente por envio_id.
    Con `origen` (latitud, longitud, codigo_pais) Fleet elige el vehículo elegible MÁS CERCANO."""
    cuerpo = {
        "envio_id": str(envio_id),
        "peso_kg": requisitos.get("peso_kg"),
        "tipo_carga": requisitos.get("tipo_carga") or "general",
        "es_hazmat": bool(requisitos.get("es_hazmat")),
    }
    if requisitos.get("volumen_m3"):
        cuerpo["volumen_m3"] = requisitos["volumen_m3"]
    if origen:
        cuerpo["origen"] = {k: origen.get(k) for k in ("latitud", "longitud", "codigo_pais") if origen.get(k) is not None}
    if excluir:
        cuerpo["excluir_vehiculos"] = [str(v) for v in excluir]

    resp = await _post("/reservas/", cuerpo)
    if resp.status_code in (200, 201):
        return resp.json()
    if resp.status_code == 409:
        try:
            mensaje = resp.json()["detail"]["mensaje"]
        except Exception:
            mensaje = "No hay un vehículo y conductor compatibles disponibles"
        raise SinDisponibilidad(mensaje)
    raise FlotaNoDisponible(f"Fleet rechazó la reserva (HTTP {resp.status_code}): {resp.text[:200]}")


async def reservar_compartida(envio_id, vehiculo_id, requisitos: dict) -> dict:
    """Suma el envío al viaje en curso de `vehiculo_id`. Fleet valida peso, volumen y compatibilidad bajo candado.
    Idempotente por envio_id. Lanza NoCabe si no es posible."""
    cuerpo = {
        "envio_id": str(envio_id),
        "vehiculo_id": str(vehiculo_id),
        "peso_kg": requisitos.get("peso_kg"),
        "tipo_carga": requisitos.get("tipo_carga") or "general",
        "es_hazmat": bool(requisitos.get("es_hazmat")),
    }
    if requisitos.get("volumen_m3"):
        cuerpo["volumen_m3"] = requisitos["volumen_m3"]
    resp = await _post("/reservas/compartida", cuerpo)
    if resp.status_code in (200, 201):
        return resp.json()
    if resp.status_code in (404, 409):
        try:
            detalle = resp.json()["detail"]
            raise NoCabe(detalle.get("codigo", "NO_CABE"), detalle.get("mensaje", "No cabe en ese vehículo"))
        except NoCabe:
            raise
        except Exception:
            raise NoCabe("NO_CABE", "No cabe en ese vehículo")
    raise FlotaNoDisponible(f"Fleet rechazó la carga compartida (HTTP {resp.status_code}): {resp.text[:200]}")


async def liberar(envio_id, sin_movimiento: bool = False) -> dict:
    """Libera la reserva del envío en Fleet. Es idempotente: repetirlo no hace daño.
    `sin_movimiento=True` solo cuando el vehículo nunca salió (conserva su última ubicación real)."""
    cuerpo = {"envio_id": str(envio_id)}
    if sin_movimiento:
        cuerpo["sin_movimiento"] = True
    resp = await _post("/reservas/liberar", cuerpo)
    if resp.status_code == 200:
        return resp.json()
    raise FlotaNoDisponible(f"Fleet rechazó la liberación (HTTP {resp.status_code})")