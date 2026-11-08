"""Test fixtures: dedicated PostGIS test database, per-test isolation.

The suite runs against a *real* PostgreSQL/PostGIS database (blueprint §16).
A separate database (``openaid_poc_test``) is created and migrated with the
same Alembic migrations used in development, and tables are truncated
between tests.

Configuration:
* ``TEST_DATABASE_URL`` — explicit override (used in CI/Docker).
* Otherwise derived from ``DATABASE_URL`` (same cluster, test database name),
  falling back to the local dev cluster default.
"""

from __future__ import annotations

import os
from pathlib import Path

TEST_DB_NAME = "openaid_poc_test"

_base = os.environ.get("DATABASE_URL")
if _base:
    TEST_DATABASE_URL = _base.rsplit("/", 1)[0] + "/" + TEST_DB_NAME
else:
    TEST_DATABASE_URL = f"postgresql+psycopg://openaid:openaid_dev_poc@127.0.0.1:5433/{TEST_DB_NAME}"

# Must be set before openaid_poc modules are imported anywhere.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

TABLES = [
    "quarantined_features",
    "import_batches",
    "boundary_versions",
    "administrative_units",
    "administrative_levels",
    "country_configurations",
    "data_sources",
    "countries",
]


def _admin_url() -> str:
    return TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"


def _run_migrations() -> None:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    from alembic import command

    from openaid_poc.cli import _alembic_cfg

    command.upgrade(_alembic_cfg(), "head")


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    from openaid_poc.db import create_database, database_exists

    if not database_exists(_admin_url(), TEST_DB_NAME):
        create_database(_admin_url(), TEST_DB_NAME)
    _run_migrations()
    yield
    from openaid_poc.db import get_engine

    get_engine().dispose()


@pytest.fixture(autouse=True)
def clean_db(migrated_db):
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        for table in TABLES:
            conn.execute(text(f"TRUNCATE {table} CASCADE"))
    engine.dispose()
    yield


@pytest.fixture
def db_session(clean_db):
    from openaid_poc.db import get_engine

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def client(clean_db):
    from openaid_poc.api import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------

POC_DIR = Path(__file__).resolve().parents[1]
FIXTURES = POC_DIR / "fixtures"


def seed_country_yaml(session, yaml_path: Path):
    """Register a country from its fixture country.yaml (mirrors CLI seed)."""
    import yaml

    from openaid_poc.models import AdministrativeLevel, Country, CountryConfiguration, CountryStatus

    doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    country = Country(
        iso2=doc["iso2"],
        iso3=doc["iso3"],
        name=doc["name"],
        official_name=doc.get("official_name"),
        capital=doc.get("capital"),
        region=doc.get("region"),
        status=CountryStatus(doc.get("status", "placeholder")),
    )
    session.add(country)
    session.flush()
    for level in doc.get("levels", []):
        session.add(
            AdministrativeLevel(
                country_id=country.id,
                level_number=int(level["level_number"]),
                level_name=level["level_name"],
                description=level.get("description"),
            )
        )
    session.add(
        CountryConfiguration(
            country_id=country.id,
            languages=doc.get("languages"),
            currency=doc.get("currency"),
            timezone=doc.get("timezone"),
            terminology=doc.get("terminology"),
        )
    )
    session.commit()
    return country


def seed_three_countries(session):
    """XA (2 levels), XB (3 levels), XC (4 levels) from the synthetic fixtures."""
    countries = {}
    for dirname in ("XA_alandra", "XB_boroland", "XC_cyria"):
        c = seed_country_yaml(session, FIXTURES / dirname / "country.yaml")
        countries[c.iso3] = c
    return countries


def import_fixture(session, country, fixture_dir: str):
    """Import a fixture's boundary.geojson through the real ingestion path."""
    from datetime import date

    from openaid_poc.ingestion import ImportMeta, ingest_geojson_bytes
    from openaid_poc.models import DataSource, ImportFormat

    data = (FIXTURES / fixture_dir / "boundary.geojson").read_bytes()
    source = DataSource(
        name=f"Synthetic fixture {country.iso3}",
        type="fixture",
        licence="CC0 (synthetic)",
        is_synthetic=True,
    )
    session.add(source)
    session.flush()
    meta = ImportMeta(
        country_id=country.id,
        country_iso3=country.iso3,
        configured_levels={l.level_number: l.level_name for l in country.administrative_levels},
        source=source,
        reference_date=date(2026, 1, 1),
        filename=f"{fixture_dir}.geojson",
        format=ImportFormat.geojson,
    )
    batch, report = ingest_geojson_bytes(session, meta, data)
    session.commit()
    return batch, report
