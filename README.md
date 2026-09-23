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