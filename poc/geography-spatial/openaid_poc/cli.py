"""Command-line interface for the geography & spatial PoC.

Examples
--------
    python -m openaid_poc.cli init-db
    python -m openaid_poc.cli seed-countries fixtures
    python -m openaid_poc.cli import fixtures/XA_alandra/boundary.geojson \
        --country XA --source-name "Synthetic fixture" --synthetic
    python -m openaid_poc.cli import real/KEN_admin.gpkg --country KEN --format gpkg
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import select

from .config import REPO_ROOT
from .db import session_scope
from .models import AdministrativeLevel, Country, CountryConfiguration, CountryStatus


def _alembic_cfg() -> "object":
    from alembic.config import Config

    pkg_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(pkg_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(pkg_root / "migrations"))
    return cfg


def cmd_init_db(args: argparse.Namespace) -> int:
    from alembic import command

    command.upgrade(_alembic_cfg(), "head")
    print("database schema is up to date")
    return 0


def _upsert_country_from_yaml(session, path: Path) -> tuple[str, str]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    iso3 = str(doc["iso3"]).upper()
    existing = session.execute(select(Country).where(Country.iso3 == iso3)).scalar_one_or_none()
    if existing is not None:
        return iso3, "already-present"

    country = Country(
        iso2=str(doc["iso2"]).upper(),
        iso3=iso3,
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
            configuration={"fixture_dir": str(path.parent.name)},
        )
    )
    return iso3, "created"


def cmd_seed_countries(args: argparse.Namespace) -> int:
    fixtures_dir = Path(args.fixtures_dir).resolve()
    yamls = sorted(fixtures_dir.glob("*/country.yaml"))
    if not yamls:
        print(f"no */country.yaml files under {fixtures_dir}", file=sys.stderr)
        return 1
    with session_scope() as session:
        for path in yamls:
            iso3, outcome = _upsert_country_from_yaml(session, path)
            print(f"{iso3}: {outcome}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from .ingestion import ImportMeta, ingest_geojson_bytes, ingest_gpkg_file
    from .models import DataSource, ImportFormat

    path = Path(args.file).resolve()
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1

    fmt = ImportFormat(args.format)
    with session_scope() as session:
        country = session.execute(select(Country).where(Country.iso3 == args.country.upper())).scalar_one_or_none()
        if country is None:
            print(f"country {args.country.upper()} is not configured; run seed-countries first", file=sys.stderr)
            return 1

        source = None
        if args.source_name:
            from .models import DataSource as DS

            source = session.execute(
                select(DS).where(DS.name == args.source_name)
            ).scalar_one_or_none()
            if source is None:
                source = DS(
                    name=args.source_name,
                    licence=args.source_licence,
                    publisher=args.source_publisher,
                    url=args.source_url,
                    is_synthetic=args.synthetic,
                    metadata_={"created_via": "cli"},
                )
                session.add(source)
                session.flush()

        meta = ImportMeta(
            country_id=country.id,
            country_iso3=country.iso3,
            configured_levels={l.level_number: l.level_name for l in country.administrative_levels},
            source=source,
            reference_date=date.fromisoformat(args.reference_date) if args.reference_date else None,
            upsert=args.upsert,
            filename=path.name,
            format=fmt,
        )

        if fmt == ImportFormat.geojson:
            batch, report = ingest_geojson_bytes(session, meta, path.read_bytes())
        else:
            import tempfile

            with tempfile.TemporaryDirectory(prefix="openaid_import_") as tmp:
                tmp_path = Path(tmp) / path.name
                tmp_path.write_bytes(path.read_bytes())
                batch, report = ingest_gpkg_file(session, meta, tmp_path, layer=args.layer)

    print(json.dumps({"batch_id": str(batch.id), "status": batch.status.value, "report": report.to_dict()}, indent=2))
    return 0 if batch.status.value != "failed" else 2


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .config import get_settings

    settings = get_settings()
    uvicorn.run("openaid_poc.api:app", host=settings.api_host, port=args.port or settings.api_port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openaid_poc", description="OpenAid geography & spatial PoC")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db", help="create/upgrade the schema via Alembic")
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("seed-countries", help="register countries from fixtures/*/country.yaml")
    p.add_argument("fixtures_dir", nargs="?", default=str(REPO_ROOT / "poc" / "geography-spatial" / "fixtures"))
    p.set_defaults(func=cmd_seed_countries)

    p = sub.add_parser("import", help="ingest a GeoJSON or GeoPackage boundary file")
    p.add_argument("file")
    p.add_argument("--country", required=True, help="target country ISO3 (must be configured)")
    p.add_argument("--format", choices=["geojson", "gpkg"], default=None, help="default: by extension")
    p.add_argument("--layer", default=None, help="GeoPackage layer name (default: first layer)")
    p.add_argument("--source-name", default=None)
    p.add_argument("--source-licence", default=None)
    p.add_argument("--source-publisher", default=None)
    p.add_argument("--source-url", default=None)
    p.add_argument("--synthetic", action="store_true", help="mark the source as synthetic test data")
    p.add_argument("--reference-date", default=None, help="boundary reference date, YYYY-MM-DD")
    p.add_argument("--upsert", action="store_true", help="existing codes receive a new boundary version")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("serve", help="run the API server")
    p.add_argument("--port", type=int, default=None)
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "import" and args.format is None:
        args.format = "gpkg" if args.file.lower().endswith((".gpkg", ".geopackage")) else "geojson"
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
