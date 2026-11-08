"""Runtime configuration, read from environment (12-factor).

A ``.env`` file at the repository root is honoured for local development;
real deployments set environment variables directly. Secrets never live in
source control.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Repo root is two levels above this package's directory
# (poc/geography-spatial/openaid_poc/config.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(REPO_ROOT / ".env")

DEFAULT_DB_URL = "postgresql+psycopg://openaid:openaid_dev_poc@127.0.0.1:5433/openaid_poc"

SRID = 4326
ALLOWED_GEOMETRY_TYPES = {"Polygon", "MultiPolygon"}


class Settings:
    def __init__(self) -> None:
        self.database_url: str = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
        self.api_host: str = os.environ.get("OPENAID_API_HOST", "0.0.0.0")
        self.api_port: int = int(os.environ.get("OPENAID_API_PORT", "8000"))
        self.api_log_level: str = os.environ.get("OPENAID_API_LOG_LEVEL", "info")
        self.max_upload_mb: int = int(os.environ.get("OPENAID_MAX_UPLOAD_MB", "50"))
        self.max_features: int = int(os.environ.get("OPENAID_MAX_FEATURES", "50000"))

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
