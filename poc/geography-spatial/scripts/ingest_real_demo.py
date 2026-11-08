#!/usr/bin/env python
"""REAL-DATA demonstration for the OpenAid geography PoC.

Ingests one real country's administrative boundaries from the open-source
`crisis-baseline-kit` project (https://github.com/alfredshingai/crisis-baseline-kit)
release bundle, which packages OCHA COD-AB boundaries obtained via HDX.

Provenance (recorded in the database as part of this run):
* Boundary source : Central Statistics Office via HDX (COD-AB)
* Licence         : CC BY-IGO (attribution required; redistribution permitted)
* Bundle          : crisis-baseline-kit v0.5.0 release, per-country baseline zip
* Reference date  : pinned in the bundle manifest (source version + retrieval date)

This is the ONLY real-data demo; everything else in the PoC is synthetic.
Run:

    python scripts/ingest_real_demo.py [--bundle-dir DIR] [--download]

Without --bundle-dir/--download the script looks for an extracted
``swz-baseline-*`` directory under the system temp directory (where the
setup instructions place it).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import shapely
from sqlalchemy import select

from openaid_poc.db import session_scope
from openaid_poc.ingestion import ImportMeta, ingest_geojson_bytes, ingest_gpkg_file
from openaid_poc.models import (
    AdministrativeLevel,
    AdministrativeUnit,
    Country,
    CountryConfiguration,
    CountryStatus,
    DataSource,
    ImportFormat,
    VerificationStatus,
)

RELEASE_URL = (
    "https://github.com/alfredshingai/crisis-baseline-kit/releases/download/"
    "v0.5.0/swz-baseline-2026-11-01.zip"
)
ISO3 = "SWZ"

LEVELS = {
    1: {
        "level_name": "Region (admin-1)",
        "description": "Eswatini first-level divisions (4); local terminology "
        "confirmation is part of full country onboarding review.",
    },
    2: {
        "level_name": "Tinkhundla (admin-2)",
        "description": "Eswatini second-level divisions (55 tinkhundla).",
    },
}


def _contract_feature(props: dict, geometry: dict, admin_level: int) -> dict:
    """Map COD-AB properties onto the PoC property contract."""
    if admin_level == 1:
        code, name = props["adm1_pcode"], props["adm1_name"]
        parent = None
    else:
        code, name = props["adm2_pcode"], props["adm2_name"]
        parent = props.get("adm1_pcode")
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "country_iso3": ISO3,
            "official_code": code,
            "source_unit_id": code,
            "name": name,
            "admin_level": admin_level,
            "parent_code": parent,
            # original COD-AB properties ride along for provenance
            "codab": {k: v for k, v in props.items()},
        },
    }


def _register_country_and_source(session, bundle_dir: Path, source_dir: Path) -> DataSource:
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    admin_layer = next(l for l in manifest["layers"] if l["layer"] == "admin_boundaries")

    country = session.execute(select(Country).where(Country.iso3 == ISO3)).scalar_one_or_none()
    if country is None:
        country = Country(
            iso2="SZ",
            iso3=ISO3,
            name="Eswatini",
            official_name="Kingdom of Eswatini",
            capital="Mbabane (executive), Lobamba (legislative, royal)",
            region="Southern Africa",
            status=CountryStatus.placeholder,
        )
        session.add(country)
        session.flush()
        for number, spec in LEVELS.items():
            session.add(
                AdministrativeLevel(
                    country_id=country.id,
                    level_number=number,
                    level_name=spec["level_name"],
                    description=spec["description"],
                )
            )
        session.add(
            CountryConfiguration(
                country_id=country.id,
                languages=["English", "siSwati"],
                currency="SZL (Eswatini Lilangeni)",
                timezone="Africa/Mbabane (UTC+02:00)",
                configuration={"onboarding": "real-data demo via crisis-baseline-kit"},
            )
        )
        session.flush()

    source = session.execute(
        select(DataSource).where(DataSource.name == "OCHA COD-AB Eswatini (via crisis-baseline-kit v0.5.0)")
    ).scalar_one_or_none()
    if source is None:
        source_version = str(admin_layer.get("source_version", ""))[:10]
        source = DataSource(
            name="OCHA COD-AB Eswatini (via crisis-baseline-kit v0.5.0)",
            type="national administrative boundaries",
            publisher="Central Statistics Office Eswatini via OCHA HDX; packaged by crisis-baseline-kit",
            url=admin_layer["source_urls"][0],
            licence="CC BY-IGO (Creative Commons Attribution 4.0 for Intergovernmental Organisations)",
            attribution=admin_layer["attribution"],
            reference_date=date.fromisoformat(source_version) if source_version else None,
            metadata_={
                "baseline_id": manifest["baseline_id"],
                "retrieved_at": admin_layer["retrieved_at"],
                "source_version": admin_layer["source_version"],
                "raw_files_sha256": {f["name"]: f["sha256"] for f in admin_layer["raw_files"]},
                "bundle_url": RELEASE_URL,
                "packaged_by": "crisis-baseline-kit (open source, MIT)",
            },
        )
        session.add(source)
        session.flush()
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, default=None, help="extracted swz-baseline-* directory")
    parser.add_argument("--download", action="store_true", help="download the release zip first")
    args = parser.parse_args()

    bundle_dir = args.bundle_dir
    if bundle_dir is None:
        # look in the default temp location used by the setup instructions
        tmp = Path(tempfile.gettempdir()) / "cbk_demo"
        matches = sorted(tmp.glob("swz-baseline-*"))
        if not matches and args.download:
            import urllib.request

            tmp.mkdir(parents=True, exist_ok=True)
            zpath = tmp / "swz.zip"
            print(f"downloading {RELEASE_URL} …")
            urllib.request.urlretrieve(RELEASE_URL, zpath)
            with zipfile.ZipFile(zpath) as z:
                z.extractall(tmp)
            matches = sorted(tmp.glob("swz-baseline-*"))
        if not matches:
            print(
                "bundle not found; run with --download or pass --bundle-dir "
                "pointing at an extracted swz-baseline-* directory",
                file=sys.stderr,
            )
            return 1
        bundle_dir = matches[0]

    data_dir = bundle_dir / "data"
    print(f"using bundle: {bundle_dir}")

    with session_scope() as session:
        source = _register_country_and_source(session, bundle_dir, data_dir)
        country = session.execute(select(Country).where(Country.iso3 == ISO3)).scalar_one()
        reference = source.reference_date

        meta = ImportMeta(
            country_id=country.id,
            country_iso3=ISO3,
            configured_levels={l.level_number: l.level_name for l in country.administrative_levels},
            source=source,
            reference_date=reference,
            filename="admin1.geojson (COD-AB)",
            format=ImportFormat.geojson,
        )

        # ---- level 1 via GeoJSON -------------------------------------------
        admin1 = json.loads((data_dir / "admin1.geojson").read_text(encoding="utf-8"))
        features1 = [_contract_feature(f["properties"], f["geometry"], 1) for f in admin1["features"]]
        batch1, report1 = ingest_geojson_bytes(session, meta, json.dumps(features1 and {"type": "FeatureCollection", "features": features1}).encode())
        print(f"admin1 (GeoJSON): {report1.status.value} — imported {report1.imported}, quarantined {report1.quarantined}")

        # ---- level 2 via GeoPackage (second format, real data) --------------
        import geopandas as gpd

        gdf = gpd.read_file(bundle_dir / "cbk_baseline.gpkg", layer="admin2")
        assert gdf.crs is not None and gdf.crs.to_epsg() == 4326, "expected EPSG:4326"
        records = []
        for _, row in gdf.iterrows():
            props = {k: (None if row[k] is None else str(row[k])) for k in ("adm2_pcode", "adm2_name", "adm1_pcode")}
            records.append(
                {
                    "country_iso3": ISO3,
                    "official_code": props["adm2_pcode"],
                    "source_unit_id": props["adm2_pcode"],
                    "name": props["adm2_name"],
                    "admin_level": 2,
                    "parent_code": props["adm1_pcode"],
                    "codab": props,
                }
            )
        contract_gdf = gpd.GeoDataFrame(
            __import__("pandas").DataFrame(records), geometry=gdf.geometry.values, crs="EPSG:4326"
        )
        with tempfile.TemporaryDirectory(prefix="openaid_real_") as tmp:
            tmp_gpkg = Path(tmp) / "swz_admin2_contract.gpkg"
            contract_gdf.to_file(tmp_gpkg, layer="admin2", driver="GPKG")
            meta2 = ImportMeta(
                country_id=country.id,
                country_iso3=ISO3,
                configured_levels={l.level_number: l.level_name for l in country.administrative_levels},
                source=source,
                reference_date=reference,
                filename="cbk_baseline.gpkg:admin2 (contract-converted)",
                format=ImportFormat.gpkg,
            )
            batch2, report2 = ingest_gpkg_file(session, meta2, tmp_gpkg, layer="admin2")
        print(f"admin2 (GeoPackage): {report2.status.value} — imported {report2.imported}, quarantined {report2.quarantined}")

        # ---- spatial demo on real coordinates --------------------------------
        # Mbabane city centre.
        lon, lat = 31.1360, -26.3180
        matches = (
            session.execute(
                select(AdministrativeUnit)
                .join(AdministrativeLevel, AdministrativeLevel.id == AdministrativeUnit.administrative_level_id)
                .where(
                    AdministrativeUnit.country_id == country.id,
                    shapely_sql_cover(lon, lat),
                )
                .order_by(AdministrativeLevel.level_number)
            ).scalars().all()
        )
        chain = [f"{u.official_code} {u.name} ({u.administrative_level.level_name})" for u in matches]
        print()
        print(f"point-in-polygon demo — Mbabane ({lon}, {lat}):")
        for link in chain:
            print(f"  · {link}")

        total = session.execute(
            select(__import__("sqlalchemy").func.count(AdministrativeUnit.id)).where(
                AdministrativeUnit.country_id == country.id
            )
        ).scalar_one()
        print()
        print(f"Eswatini units stored: {total}; boundary source: {source.name}")
        print(f"licence: {source.licence}")
    return 0


def shapely_sql_cover(lon: float, lat: float):
    from sqlalchemy import func

    from openaid_poc.config import SRID

    return func.ST_Covers(AdministrativeUnit.geometry, func.ST_SetSRID(func.ST_MakePoint(lon, lat), SRID))


if __name__ == "__main__":
    raise SystemExit(main())
