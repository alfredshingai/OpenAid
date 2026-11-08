"""Backend test configuration: dedicated PostGIS test database.

The suite runs against a real PostgreSQL/PostGIS database created and
migrated with the application's own Alembic revisions (same pattern as the
§16 PoC suite).
"""

from __future__ import annotations

import os

TEST_DB_NAME = "openaid_test"

_base = os.environ.get("DATABASE_URL")
if _base:
    TEST_DATABASE_URL = _base.rsplit("/", 1)[0] + "/" + TEST_DB_NAME
else:
    TEST_DATABASE_URL = "postgresql+psycopg://openaid:openaid_dev_poc@127.0.0.1:5433/openaid_test"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

TABLES = [
    "quarantined_features",
    "import_batches",
    "boundary_versions",
    "administrative_units",
    "administrative_levels",
    "country_configurations",
    "indicator_observations",
    "comparability_assessments",
    "indicator_definitions",
    "facility_services",
    "facility_organisations",
    "facilities",
    "facility_types",
    "organisation_sectors",
    "organisation_locations",
    "organisations",
    "dataset_files",
    "dataset_versions",
    "datasets",
    "data_sources",
    "countries",
]

# Extracted crisis-baseline-kit bundle used for real-data tests. When absent,
# real-data tests skip gracefully (synthetic coverage still runs).
BUNDLE_DIR = os.environ.get("OPENAID_TEST_BUNDLE_DIR", "")


def _admin_url() -> str:
    return TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"


def _run_migrations() -> None:
    from alembic import command

    backend_root = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
    sys_path = os.path.abspath(backend_root)
    import sys

    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from alembic.config import Config

    cfg = Config(os.path.join(sys_path, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(sys_path, "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    from openaid_core.db import create_database, database_exists, get_engine, reset_engine

    reset_engine()
    if not database_exists(_admin_url(), TEST_DB_NAME):
        create_database(_admin_url(), TEST_DB_NAME)
    _run_migrations()
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def clean_db(migrated_db):
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        for table in TABLES:
            conn.execute(text(f"TRUNCATE {table} CASCADE"))
    engine.dispose()
    yield
    from openaid_core.db import reset_engine

    reset_engine()


@pytest.fixture
def client(clean_db):
    from openaid_api.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_bundle(clean_db):
    """Seed the full Phase 1 dataset (requires the extracted SWZ bundle)."""
    if not BUNDLE_DIR:
        pytest.skip("OPENAID_TEST_BUNDLE_DIR not set (extract a swz-baseline-* bundle to enable)")
    from pathlib import Path

    from openaid_core.seed.phase1 import run as seed_run

    seed_run(Path(BUNDLE_DIR))
