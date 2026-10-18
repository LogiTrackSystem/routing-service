# ---------- Etapa 1: build (herramientas de compilacion, no viajan a la imagen final) ----------
FROM python:3.13-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Etapa 2: runtime (imagen final, liviana) ----------
FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

EXPOSE 8003

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8003}"]