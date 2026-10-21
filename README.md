# Routing Service

Microservicio de LogiTrack que calcula y asigna rutas. Consume `shipment.created`
de RabbitMQ, sugiere un vehículo consultando a Fleet Service por REST, crea la
ruta y publica `route.assigned`. Mantiene historial de cada recálculo.

## Stack
FastAPI + SQLAlchemy + Alembic + PostgreSQL + aio-pika (RabbitMQ) + httpx.

## Levantar en local
1. `python -m venv venv && venv\Scripts\activate`
2. `pip install -r requirements.txt`
3. Copiar `.env.example` a `.env` y completar.
4. Crear la base de datos `routing_db` en tu PostgreSQL local.
5. `alembic upgrade head`
6. `uvicorn app.main:app --reload --port 8003`

## Endpoints
- `GET /health`
- `POST /rutas/` — crear ruta manualmente
- `GET /rutas/` — listar (filtro opcional `envio_id`)
- `GET /rutas/{id}` — detalle
- `GET /rutas/{id}/historial` — historial de recálculos
- `PATCH /rutas/{id}/recalcular` — recalcula y guarda snapshot anterior

## Eventos
- Consume: `shipment.created`
- Publica: `route.assigned`

## Asignación por cercanía, tramo en vacío y carga compartida

`intentar_asignar` hace, en este orden:

1. **Compartir primero** (`CARGA_COMPARTIDA_ACTIVA`): busca vehículos que ya van (o están por ir) por la misma ruta y a los que el envío se puede subir **sin desvío**: su origen y su destino deben ser el origen, el destino o una parada del catálogo de la ruta del vehículo (a menos de `PARADA_MAX_DESVIO_KM` de la vía), el destino después del origen, y el vehículo todavía no puede haber pasado el punto de recogida (`MARGEN_RECOGIDA_KM`). Peso, volumen, HAZMAT y tipo de carga los valida Fleet bajo candado. La ruta resultante queda con `modo=compartida`, `ruta_anfitriona_id`, `km_recogida` y `km_entrega`.
2. **Vehículo exclusivo más cercano**: pide a Fleet la reserva con el `origen` de la ruta maestra. El vehículo saldrá desde **donde realmente está**: Routing calcula el tramo en vacío (`reposicion`: distancia, duración, geometría, `fuente` = `osrm` o `estimada`). Ese tramo no entra en `distancia_km` (lo que factura Billing) y sí en la hora estimada de llegada. Si un vehículo no tiene carretera hasta el origen se devuelve y se prueba otro.

Si Fleet no conoce una ubicación fiable no se inventa un tramo: `reposicion.motivo` queda en `UBICACION_DESCONOCIDA` o `UBICACION_NO_FIABLE` y Tracking decide con su última lectura real.

Cuando un vehículo termina **sin entregar** (devuelto, cancelado o entrega manual a mitad de camino), las cargas compartidas que aún no habían subido se liberan y vuelven a la cola; el barrido periódico también revisa este caso.

**Endpoints nuevos:** `GET /trayecto/?desde_lat=&desde_lon=&hasta_lat=&hasta_lon=` (tramo por carretera; lo usa Tracking). `GET /rutas/` ahora muestra `modo`, `ruta_anfitriona_id`, `km_recogida`, `km_entrega` y `reposicion` (sin la geometría).

**Eventos:** `route.assigned` suma `modo`, `ruta_anfitriona_id`, `km_recogida`, `km_entrega`, `origen`, `destino` y `reposicion`. Consume además `tracking.trip_started` (marca en curso las cargas compartidas) y `tracking.shared_load_missed` (Tracking avisa que una carga compartida ya no puede subir: se libera su reserva y vuelve a la cola, una sola vez). `telemetry.raw` ahora trae `ruta_id` y `fase`; las lecturas de la fase `reposicion` no cuentan para `distancia_km`.

**Variables nuevas:** `OSRM_INTENTOS_REPOSICION`, `OSRM_TIMEOUT_REPOSICION_S`, `UMBRAL_MISMO_LUGAR_KM`, `CARGA_COMPARTIDA_ACTIVA`, `PARADA_MAX_DESVIO_KM`, `MARGEN_RECOGIDA_KM`, `TRAMO_MINIMO_COMPARTIDO_KM`, `MAX_ANFITRIONES_EVALUADOS`, `DB_LOCK_TIMEOUT_MS`, `ESPERA_RUTA_OCUPADA_S`, `INTENTOS_RUTA_OCUPADA` (ver `.env.example`). Ningún manejador de eventos espera un candado de fila de forma bloqueante: si la ruta la tiene otra tarea se reintenta con `asyncio.sleep`.

**Migración** `b81f3c0d7a24` (solo agrega columnas con valor por defecto). **Pruebas:** `python -m pytest tests` (SQLite en memoria y un Fleet simulado).
