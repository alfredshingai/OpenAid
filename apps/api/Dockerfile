FROM python:3.12-slim

# GeoPackage/GDAL runtime libraries used by pyogrio
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal32 libgeos-c1v5 libproj25 libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Domain library first (better layer caching)
COPY backend/pyproject.toml backend/README.md ./backend/
COPY backend/openaid_core ./backend/openaid_core
COPY backend/migrations ./backend/migrations
COPY backend/alembic.ini ./backend/alembic.ini
RUN pip install --no-cache-dir ./backend

COPY apps/api/pyproject.toml ./apps/api/
COPY apps/api/openaid_api ./apps/api/openaid_api
RUN pip install --no-cache-dir ./apps/api

ENV OPENAID_API_HOST=0.0.0.0
EXPOSE 8000

WORKDIR /app/backend
CMD ["uvicorn", "openaid_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
