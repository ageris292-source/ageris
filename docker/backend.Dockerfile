FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    AEGIS_CONFIG_PATH=/app/config/aegis.yaml
WORKDIR /app/backend
# libgomp: OpenMP runtime required by LightGBM (walk-forward model, Phase 10).
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
COPY backend/app ./app
# CPU-only torch for FinBERT / sentence embeddings (the [ml] extra).
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install ".[ml]"

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY config /app/config

RUN useradd --create-home --uid 10001 aegis
USER aegis
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
