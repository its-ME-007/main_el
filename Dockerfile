# One container: FastAPI (backend/urban/api.py) serves the built UI, the exported results and the pipeline job runner.
# Data stays outside the image: mount backend/data (OSM extract, nets, runs, exports). See docker-compose.yml.

# 1. build the UI
FROM node:20.18-slim AS ui
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. backend + SUMO. The eclipse-sumo wheel ships sumo, netconvert, marouter and tools/ (randomTrips.py).
FROM python:3.12.8-slim
# libexpat1 (pyosmium, netconvert), libatomic1, and the X11/GL libs the eclipse-sumo binaries link against even
# when run headless; slim images leave them all out
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 libatomic1 libx11-6 libxext6 libxrender1 libgl1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
# big wheels (eclipse-sumo ~100 MB, geopandas stack) time out at uv's default 30 s on slow links
ENV UV_HTTP_TIMEOUT=300
RUN uv sync --frozen --no-dev && uv pip install eclipse-sumo==1.28.0
COPY backend/urban ./urban
COPY --from=ui /app/frontend/dist /app/frontend/dist
ENV SUMO_HOME=/app/backend/.venv/lib/python3.12/site-packages/sumo \
    PATH=/app/backend/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "urban.api:app", "--host", "0.0.0.0", "--port", "8000"]
