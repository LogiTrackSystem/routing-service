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

---

<!-- entrega-final -->

## Descripción

Catálogo de ubicaciones, rutas maestras por carretera (OSRM) y asignación de vehículo y conductor mediante una Saga con reintentos y compensación; también la carga compartida.

- **Puerto local:** 8003   ·   **Despliegue activo:** <https://logitrack-routing.onrender.com> (`/health` y `/metrics` públicos)
- **Imagen Docker:** `<usuario-dockerhub>/logitrack-routing`   ·   **Repositorio de CI/CD:** `LogiTrackSystem/pipelines`

## Variables de entorno

Copia `.env.example` como `.env` y completa los valores. El `.env` **no se sube** al repositorio.

| Variable | Para qué sirve |
|---|---|
| `DATABASE_URL` | Conexión a la base PostgreSQL del servicio (`postgresql://usuario:clave@host:5432/<base>`). Es un secreto. |
| `RABBITMQ_URL` | URL AMQP del bus de eventos RabbitMQ (CloudAMQP en producción). Es un secreto. |
| `FLEET_SERVICE_URL` | URL base de Fleet Service, sin barra final (en local `http://localhost:<puerto>`). |
| `SHIPMENT_SERVICE_URL` | URL base de Shipment Service, sin barra final (en local `http://localhost:<puerto>`). |
| `OSRM_URL` | Servidor OSRM para calcular rutas por carretera (por defecto el público de OSRM). |
| `INTERNAL_API_KEY` | Clave compartida entre el gateway y los servicios: exige la cabecera `X-Internal-Key` en todas las rutas salvo `/health` y `/metrics`. Vacía = sin restricción (solo local). Es un secreto. |
| `OSRM_INTENTOS` | Reintentos de consulta a OSRM. |
| `OSRM_TIMEOUT_S` | Tiempo de espera (s) por intento de OSRM. |
| `OSRM_INTENTOS_REPOSICION` | Reintentos de OSRM para el tramo en vacío. |
| `OSRM_TIMEOUT_REPOSICION_S` | Tiempo de espera (s) de OSRM para el tramo en vacío. |
| `UMBRAL_MISMO_LUGAR_KM` | Por debajo de esta distancia el vehículo "ya está en el origen". |
| `CARGA_COMPARTIDA_ACTIVA` | `false` apaga la carga compartida. |
| `PARADA_MAX_DESVIO_KM` | Una parada cuenta como "sobre la ruta" si está a menos de estos km de la carretera. |
| `MARGEN_RECOGIDA_KM` | Km mínimos antes del punto de recogida para subir carga compartida. |
| `TRAMO_MINIMO_COMPARTIDO_KM` | Tramo mínimo (km) de la carga compartida. |
| `DB_LOCK_TIMEOUT_MS` | Espera máxima (ms) por un candado de fila antes de fallar; 0 = sin límite. |
| `MAX_ANFITRIONES_EVALUADOS` | Máximo de rutas en viaje evaluadas como anfitrionas. |
| `ESPERA_RUTA_OCUPADA_S` | Espera (s) entre reintentos cuando la ruta está tomada por otra tarea. |
| `INTENTOS_RUTA_OCUPADA` | Número de esos reintentos. |

## Documentación de la API

- **Local** (sin `INTERNAL_API_KEY`): <http://localhost:8003/docs> (Swagger) y `http://localhost:8003/openapi.json`.
- **Producción:** el servicio solo atiende peticiones que llegan por el gateway (con `INTERNAL_API_KEY` activa su `/docs` no es público); la documentación de todas las rutas está en <https://logitrack-gateway.onrender.com/docs>.

## Base de datos

- Migraciones con Alembic (`alembic/`): `alembic upgrade head` (el `Dockerfile` ya lo ejecuta al arrancar).
- `db/esquema.sql`: esquema completo de `routing_db` generado desde las migraciones.
- Datos de ejemplo: este servicio se alimenta de eventos y llamadas de otros servicios; se generan ejecutando el flujo completo (por ejemplo `_pruebas/casos.py` del proyecto).
- Respaldo y restauración: ver `db/README.md`.

## Pruebas

Con el entorno virtual activo y `pip install -r requirements-dev.txt`:

```
pytest tests/unit                    # 2 pruebas unitarias
pytest tests/integration             # 1 prueba de integración
pytest --cov=app --cov-report=term   # toda la suite con cobertura
```

| Prueba | Qué verifica |
|---|---|
| Unitaria 1 | `geo.calcular_paradas` |
| Unitaria 2 | `asignacion.procesar_shipment_created` |
| Integración | evento `shipment.created` → asignación de vehículo → consulta de la ruta por API |

Archivos: `tests/unit/` y `tests/integration/` (test_calcular_paradas.py, test_envio_creado.py, test_flujo_asignacion.py). Cobertura de `app/` medida: **≈ 67 %**; en cada push y Pull Request GitHub Actions la recalcula y guarda `coverage.xml` como artefacto (`cobertura-routing`).

## Métricas y monitoreo

Expone `GET /metrics` (formato Prometheus: `http_requests_total` y `http_request_duration_*`). Prometheus y el dashboard de Grafana están en el repositorio `logitrack-monitoring`.

## CI/CD

- `.github/workflows/pr.yml`: en cada push (rama distinta de `main`) y en cada Pull Request a `main` ejecuta el CI reutilizable (lint, pruebas con cobertura, `docker build` y prueba de arranque).
- `.github/workflows/deploy.yml`: al fusionar en `main`, y solo con las pruebas en verde, publica la imagen en Docker Hub y despliega en Render (con verificación de `/health` y rollback manual).
- Detalle y estrategia de ramas: `CICD.md` en el repositorio `LogiTrackSystem/pipelines`.

