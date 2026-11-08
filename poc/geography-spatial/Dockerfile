FROM python:3.12-slim

# gdal/pyogrio runtime libraries for GeoPackage ingestion
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal32 libgeos-c1v5 libproj25 libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY openaid_poc ./openaid_poc
COPY migrations ./migrations
COPY alembic.ini ./
COPY fixtures ./fixtures
COPY scripts ./scripts
COPY tests ./tests

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "openaid_poc.api:app", "--host", "0.0.0.0", "--port", "8000"]
