"""Phase 1 seed: Africa-wide country registry + real Eswatini baseline.

Runs the full data-loading path for the public MVP:

1. All 54+ African countries as ISO-registered rows with
   ``status=placeholder`` (structure without claims about data).
2. Eswatini activated with configuration + COD-AB administrative hierarchy
   and boundaries (via the validated ingestion pipeline).
3. REAL indicator observations from the crisis-baseline-kit v0.5.0 bundle:
   WorldPop 2020 population (CC-BY 4.0), OSM road density (ODbL) and HOT OSM
   education-facility counts (ODbL) per admin-2 unit, with country-level
   aggregation for summable indicators only.
4. REAL education facilities (points) from the same bundle, assigned to
   admin-2 units by spatial join, with operational_status=unknown (OSM
   presence is not evidence of current operation).
5. Data catalogue entries for every source actually used, with licence and
   access class recorded separately.

Usage (repo root or backend/):
    python -m openaid_core.seed.phase1 --bundle-dir <extracted swz-baseline-* dir>
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from geoalchemy2 import WKTElement
from sqlalchemy import select

from ..config import SRID
from ..db import session_scope
from ..datasets.models import AccessClass, DataSource, Dataset, DatasetFile, DatasetVersion
from ..facilities.models import Facility, FacilityService, FacilityType, OperationalStatus
from ..geography.ingestion import ImportMeta, ingest_geojson_bytes, ingest_gpkg_file
from ..geography.models import (
    AdministrativeLevel,
    AdministrativeUnit,
    Country,
    CountryConfiguration,
    CountryStatus,
    ImportFormat,
)
from ..indicators.models import (
    AggregationMethod,
    IndicatorCategory,
    IndicatorDefinition,
    IndicatorObservation,
    MeasurementType,
    ValueType,
)
from .african_countries import AFRICAN_COUNTRIES

BUNDLE_RELEASE_URL = (
    "https://github.com/alfredshingai/crisis-baseline-kit/releases/download/"
    "v0.5.0/swz-baseline-2026-11-01.zip"
)

SWZ_LEVELS = {
    1: ("Region (admin-1)", "Eswatini first-level divisions (4); local terminology "
        "confirmation is part of full country onboarding review."),
    2: ("Tinkhundla (admin-2)", "Eswatini second-level divisions (55 tinkhundla)."),
}

# Indicator definitions seeded globally (factual definitions; values come from
# recorded sources only).
INDICATOR_DEFS = [
    {
        "code": "total_population",
        "name": "Total population",
        "category": IndicatorCategory.demographic,
        "unit": "persons",
        "measurement_type": MeasurementType.count,
        "aggregation_method": AggregationMethod.sum,
        "description": "Total resident population for the geography and period.",
        "methodology": "Zonal sum of WorldPop 2020 constrained 100 m gridded "
        "population estimates per administrative unit. WorldPop population "
        "figures are modelled estimates, not census counts.",
    },
    {
        "code": "population_density",
        "name": "Population density",
        "category": IndicatorCategory.demographic,
        "unit": "persons/km2",
        "measurement_type": MeasurementType.rate,
        "aggregation_method": AggregationMethod.not_aggregatable,
        "description": "Population per square kilometre for the geography.",
        "methodology": "WorldPop 2020 zonal population sum divided by unit area "
        "(source-derived); not directly aggregable across units.",
    },
    {
        "code": "education_facilities_count",
        "name": "Education facilities (mapped)",
        "category": IndicatorCategory.education,
        "unit": "facilities",
        "measurement_type": MeasurementType.count,
        "aggregation_method": AggregationMethod.sum,
        "description": "Number of education facility points mapped in the "
        "source dataset within the geography.",
        "methodology": "Count of HOT OSM education facilities (via HDX) points "
        "inside the unit boundary. Counts reflect mapping coverage, not the "
        "true number or operational status of facilities.",
    },
    {
        "code": "schools_per_10k_population",
        "name": "Mapped schools per 10,000 population",
        "category": IndicatorCategory.education,
        "unit": "facilities/10k persons",
        "measurement_type": MeasurementType.rate,
        "aggregation_method": AggregationMethod.not_aggregatable,
        "description": "Mapped education facilities per 10,000 residents.",
        "methodology": "Education facility count divided by WorldPop 2020 "
        "population (x10,000). Combines an observed count with modelled "
        "population; interpret as mapping coverage, not service availability.",
    },
    {
        "code": "road_density",
        "name": "Road density",
        "category": IndicatorCategory.infrastructure,
        "unit": "km/100km2",
        "measurement_type": MeasurementType.rate,
        "aggregation_method": AggregationMethod.not_aggregatable,
        "description": "Kilometres of mapped road per 100 km².",
        "methodology": "OSM road network length (via Geofabrik extract) per "
        "unit area, source-derived. Reflects OSM mapping coverage.",
    },
]


def seed_countries(session) -> dict[str, Country]:
    """All African countries as placeholder rows; returns by ISO3."""
    by_iso3: dict[str, Country] = {}
    for iso2, iso3, name, region, lon, lat in AFRICAN_COUNTRIES:
        country = session.execute(select(Country).where(Country.iso3 == iso3)).scalar_one_or_none()
        if country is None:
            country = Country(iso2=iso2, iso3=iso3, name=name, region=region,
                              rep_lon=lon, rep_lat=lat, status=CountryStatus.placeholder)
            session.add(country)
            session.flush()
        elif country.rep_lon is None:
            country.rep_lon, country.rep_lat = lon, lat
        by_iso3[iso3] = country
    return by_iso3


def register_sources_and_datasets(session, bundle_dir: Path) -> dict[str, DataSource]:
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    layers = {l["layer"]: l for l in manifest["layers"]}
    admin = layers["admin_boundaries"]
    population = layers.get("population", {})
    roads = layers.get("roads", {})
    schools = layers.get("schools", {})

    def _src(name, **kw) -> DataSource:
        src = session.execute(select(DataSource).where(DataSource.name == name)).scalar_one_or_none()
        if src is None:
            src = DataSource(name=name, **kw)
            session.add(src)
            session.flush()
        return src

    sources = {
        "codab": _src(
            "OCHA COD-AB Eswatini (via crisis-baseline-kit v0.5.0)",
            type="national administrative boundaries",
            publisher="Central Statistics Office Eswatini via OCHA HDX; packaged by crisis-baseline-kit",
            url=admin["source_urls"][0],
            licence="CC BY-IGO (Creative Commons Attribution 4.0 for Intergovernmental Organisations)",
            attribution=admin["attribution"],
            reference_date=_date(str(admin.get("source_version", ""))[:10]),
            metadata_={
                "retrieved_at": admin.get("retrieved_at"),
                "source_version": admin.get("source_version"),
                "raw_files_sha256": {f["name"]: f["sha256"] for f in admin.get("raw_files", [])},
                "bundle_url": BUNDLE_RELEASE_URL,
            },
        ),
        "worldpop": _src(
            "WorldPop 2020 constrained population (SWZ)",
            type="gridded population model",
            publisher="WorldPop, University of Southampton; packaged by crisis-baseline-kit",
            url="https://hub.worldpop.org/",
            licence="CC-BY 4.0",
            attribution=population.get("attribution", "WorldPop (SWZ 2020, ppp, 100 m)"),
            reference_date=date(2020, 12, 31),
            metadata_={"retrieved_at": population.get("retrieved_at"), "bundle_url": BUNDLE_RELEASE_URL},
        ),
        "schools": _src(
            "HOT OSM education facilities Eswatini (via HDX)",
            type="facility points",
            publisher="Humanitarian OpenStreetMap Team via HDX; packaged by crisis-baseline-kit",
            url=schools.get("source_urls", ["https://data.humdata.org/"])[0],
            licence="Open Database License (ODC-ODbL)",
            attribution=schools.get("attribution", "HOT OSM education facilities"),
            metadata_={"retrieved_at": schools.get("retrieved_at"), "bundle_url": BUNDLE_RELEASE_URL},
        ),
        "roads": _src(
            "OSM roads Eswatini (via Geofabrik)",
            type="road network",
            publisher="OpenStreetMap contributors via Geofabrik; packaged by crisis-baseline-kit",
            url="https://download.geofabrik.de/africa/swaziland.html",
            licence="ODbL",
            attribution="OpenStreetMap contributors",
            metadata_={"retrieved_at": roads.get("retrieved_at"), "bundle_url": BUNDLE_RELEASE_URL},
        ),
    }

    # --- data catalogue entries (access class separate from licence) -------
    catalogue = [
        (
            "ocha-codab-ewswatini-admin-boundaries",
            "Eswatini Administrative Boundaries (COD-AB)",
            "Official administrative boundaries: 4 regions (admin-1) and 55 "
            "tinkhundla (admin-2), from the Central Statistics Office via OCHA "
            "HDX, packaged by crisis-baseline-kit v0.5.0.",
            "codab", "2026-01-26",
        ),
        (
            "worldpop-2020-swz-population",
            "Eswatini Population 2020 (WorldPop 100 m)",
            "Modelled gridded population (WorldPop 2020 constrained, 100 m) "
            "summarised per administrative unit by crisis-baseline-kit.",
            "worldpop", "2020-12-31",
        ),
        (
            "hot-osm-education-facilities-swz",
            "Eswatini Education Facilities (HOT OSM via HDX)",
            "Education facility points mapped by the OSM community; counts "
            "reflect mapping coverage and imply nothing about operational "
            "status.",
            "schools", None,
        ),
        (
            "osm-roads-swz",
            "Eswatini Road Network (OSM via Geofabrik)",
            "Road network lines from OpenStreetMap; length statistics per "
            "administrative unit computed by crisis-baseline-kit.",
            "roads", None,
        ),
    ]
    for slug, title, desc, src_key, ref in catalogue:
        ds = session.execute(select(Dataset).where(Dataset.slug == slug)).scalar_one_or_none()
        if ds is None:
            ds = Dataset(
                slug=slug,
                title=title,
                description=desc,
                publisher=sources[src_key].publisher,
                licence=sources[src_key].licence,
                attribution=sources[src_key].attribution,
                access_class=AccessClass.public,
                language="en",
                spatial_coverage={"countries": ["SWZ"], "levels": ["admin1", "admin2"]},
                temporal_coverage={"start": ref} if ref else None,
                homepage_url=BUNDLE_RELEASE_URL,
                is_synthetic=False,
            )
            session.add(ds)
            session.flush()
            ds.versions.append(
                DatasetVersion(
                    version_number="v0.5.0",
                    changelog="Imported from crisis-baseline-kit v0.5.0 release bundle.",
                    published_at=datetime.now(timezone.utc),
                    source_version=manifest.get("baseline_id"),
                )
            )
            if src_key == "codab":
                ds.files.append(DatasetFile(filename="cbk_baseline.gpkg", format="gpkg", layer="admin1"))
                ds.files.append(DatasetFile(filename="cbk_baseline.gpkg", format="gpkg", layer="admin2"))
            elif src_key == "schools":
                ds.files.append(DatasetFile(filename="schools.parquet", format="parquet"))
            elif src_key == "roads":
                ds.files.append(DatasetFile(filename="roads.parquet", format="parquet"))
            else:
                ds.files.append(DatasetFile(filename="admin2.parquet", format="parquet"))
    return sources


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def ingest_swz_boundaries(session, country: Country, bundle_dir: Path, source: DataSource) -> None:
    """Activate Eswatini's hierarchy and ingest real COD-AB boundaries."""
    for number, (name, desc) in SWZ_LEVELS.items():
        exists = session.execute(
            select(AdministrativeLevel).where(
                AdministrativeLevel.country_id == country.id,
                AdministrativeLevel.level_number == number,
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(AdministrativeLevel(country_id=country.id, level_number=number, level_name=name, description=desc))
    config = session.execute(
        select(CountryConfiguration).where(CountryConfiguration.country_id == country.id)
    ).scalar_one_or_none()
    if config is None:
        session.add(
            CountryConfiguration(
                country_id=country.id,
                languages=["English", "siSwati"],
                currency="SZL (Eswatini Lilangeni)",
                timezone="Africa/Mbabane (UTC+02:00)",
                configuration={"onboarding": "crisis-baseline-kit v0.5.0 bundle"},
            )
        )
    session.flush()

    admin1 = json.loads((bundle_dir / "data" / "admin1.geojson").read_text(encoding="utf-8"))
    features1 = [_contract(f["properties"], f["geometry"], 1) for f in admin1["features"]]
    meta = ImportMeta(
        country_id=country.id,
        country_iso3=country.iso3,
        configured_levels={n: name for n, (name, _d) in SWZ_LEVELS.items()},
        source=source,
        reference_date=source.reference_date,
        filename="admin1.geojson (COD-AB)",
        format=ImportFormat.geojson,
    )
    _batch, report = ingest_geojson_bytes(
        session, meta, json.dumps({"type": "FeatureCollection", "features": features1}).encode()
    )
    print(f"  admin1 boundaries: {report.status.value} imported={report.imported} quarantined={report.quarantined}")

    gdf = gpd.read_file(bundle_dir / "cbk_baseline.gpkg", layer="admin2")
    records = []
    for _, row in gdf.iterrows():
        records.append(
            {
                "country_iso3": country.iso3,
                "official_code": str(row["adm2_pcode"]),
                "source_unit_id": str(row["adm2_pcode"]),
                "name": str(row["adm2_name"]),
                "admin_level": 2,
                "parent_code": str(row["adm1_pcode"]),
                "codab": {k: (None if row[k] is None else str(row[k])) for k in
                          ("adm0_pcode", "adm0_name", "adm1_pcode", "adm1_name", "adm2_pcode", "adm2_name")},
            }
        )
    contract = gpd.GeoDataFrame(pd.DataFrame(records), geometry=gdf.geometry.values, crs="EPSG:4326")
    with tempfile.TemporaryDirectory(prefix="openaid_seed_") as tmp:
        tmp_gpkg = Path(tmp) / "swz_admin2_contract.gpkg"
        contract.to_file(tmp_gpkg, layer="admin2", driver="GPKG")
        meta2 = ImportMeta(
            country_id=country.id,
            country_iso3=country.iso3,
            configured_levels={n: name for n, (name, _d) in SWZ_LEVELS.items()},
            source=source,
            reference_date=source.reference_date,
            filename="cbk_baseline.gpkg:admin2 (contract-converted)",
            format=ImportFormat.gpkg,
        )
        _batch, report = ingest_gpkg_file(session, meta2, tmp_gpkg, layer="admin2")
    print(f"  admin2 boundaries: {report.status.value} imported={report.imported} quarantined={report.quarantined}")


def _contract(props: dict, geometry: dict, admin_level: int) -> dict:
    if admin_level == 1:
        code, name, parent = props["adm1_pcode"], props["adm1_name"], None
    else:
        code, name, parent = props["adm2_pcode"], props["adm2_name"], props.get("adm1_pcode")
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "country_iso3": "SWZ",
            "official_code": code,
            "source_unit_id": code,
            "name": name,
            "admin_level": admin_level,
            "parent_code": parent,
            "codab": dict(props),
        },
    }


def seed_indicators(session, country: Country, bundle_dir: Path, sources: dict[str, DataSource]) -> None:
    """Insert indicator definitions and REAL per-unit observations."""
    defs_by_code: dict[str, IndicatorDefinition] = {}
    for spec in INDICATOR_DEFS:
        d = session.execute(
            select(IndicatorDefinition).where(IndicatorDefinition.code == spec["code"])
        ).scalar_one_or_none()
        if d is None:
            d = IndicatorDefinition(**spec)
            session.add(d)
            session.flush()
        defs_by_code[spec["code"]] = d

    units: dict[str, AdministrativeUnit] = {
        u.official_code: u
        for u in session.execute(
            select(AdministrativeUnit).where(AdministrativeUnit.country_id == country.id)
        ).scalars().all()
    }
    levels: dict[str, AdministrativeLevel] = {
        u.official_code: u.administrative_level for u in units.values()
    }

    df = pd.read_parquet(bundle_dir / "admin2.parquet")
    existing = set(
        session.execute(
            select(IndicatorObservation.unit_id, IndicatorObservation.indicator_definition_id)
        ).all()
    )
    existing_pairs = {(str(u), str(d)) for u, d in existing}

    obs_added = 0

    def _add_obs(unit: AdministrativeUnit | None, code: str, value, value_type: ValueType,
                 src, version: str, period: date, notes: str | None = None, sample=None) -> None:
        nonlocal obs_added
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return
        d = defs_by_code[code]
        unit_id = unit.id if unit is not None else None
        if (str(unit_id), str(d.id)) in existing_pairs:
            return
        session.add(
            IndicatorObservation(
                country_id=country.id,
                unit_id=unit_id,
                indicator_definition_id=d.id,
                period_start=period,
                period_end=period,
                value=float(value),
                value_type=value_type,
                source_id=src.id,
                dataset_version=version,
                methodology_notes=notes,
                sample_size=sample,
            )
        )
        obs_added += 1

    period = date(2020, 12, 31)
    pop_src = sources["worldpop"]
    school_src = sources["schools"]
    road_src = sources["roads"]

    admin1_totals: dict[str, float] = {}
    admin1_schools: dict[str, float] = {}
    country_pop = 0.0
    country_schools = 0.0

    for _, row in df.iterrows():
        code2 = str(row["adm2_pcode"])
        unit = units.get(code2)
        if unit is None:
            continue
        pop = row.get("population_sum")
        _add_obs(unit, "total_population", pop, ValueType.modelled, pop_src,
                 "worldpop-2020-100m", period,
                 notes="WorldPop 2020 zonal sum (modelled gridded population).")
        _add_obs(unit, "population_density", row.get("pop_density_km2"), ValueType.modelled,
                 pop_src, "worldpop-2020-100m", period,
                 notes="WorldPop population / unit area (source-derived).")
        schools = row.get("school_count")
        _add_obs(unit, "education_facilities_count", schools, ValueType.observed,
                 school_src, "hdx-hotosm-2026-11", period,
                 notes="Count of mapped education facility points; reflects mapping coverage.")
        _add_obs(unit, "schools_per_10k_population", row.get("schools_per_10k_pop"),
                 ValueType.observed, school_src, "hdx-hotosm-2026-11", period,
                 notes="Facility count per 10k WorldPop population; mapping coverage metric.")
        _add_obs(unit, "road_density", row.get("road_km_per_100km2"), ValueType.observed,
                 road_src, "geofabrik-swz-2026", period,
                 notes="OSM road km per 100 km2; reflects OSM mapping coverage.")
        if pop is not None and not pd.isna(pop):
            p1 = str(row["adm1_pcode"])
            admin1_totals[p1] = admin1_totals.get(p1, 0.0) + float(pop)
            country_pop += float(pop)
        if schools is not None and not pd.isna(schools):
            p1 = str(row["adm1_pcode"])
            admin1_schools[p1] = admin1_schools.get(p1, 0.0) + float(schools)
            country_schools += float(schools)

    # Summable indicators only — density/rate metrics are NOT aggregated.
    for pcode, total in admin1_totals.items():
        unit = units.get(pcode)
        if unit is not None:
            _add_obs(unit, "total_population", total, ValueType.modelled, pop_src,
                     "worldpop-2020-100m", period,
                     notes="Sum of admin-2 WorldPop zonal sums for this region.")
    for pcode, total in admin1_schools.items():
        unit = units.get(pcode)
        if unit is not None:
            _add_obs(unit, "education_facilities_count", total, ValueType.observed,
                     school_src, "hdx-hotosm-2026-11", period,
                     notes="Sum of admin-2 mapped facility counts.")
    if country_pop:
        _add_obs(None, "total_population", country_pop, ValueType.modelled, pop_src,
                 "worldpop-2020-100m", period,
                 notes="Country total: sum of admin-2 WorldPop zonal sums.")
    if country_schools:
        _add_obs(None, "education_facilities_count", country_schools, ValueType.observed,
                 school_src, "hdx-hotosm-2026-11", period,
                 notes="Country total: sum of admin-2 mapped facility counts.")

    print(f"  indicator observations added: {obs_added}")


def seed_facilities(session, country: Country, bundle_dir: Path, sources: dict[str, DataSource]) -> None:
    """REAL education facility points from the bundle, assigned to units."""
    ftype = session.execute(
        select(FacilityType).where(FacilityType.code == "education_school")
    ).scalar_one_or_none()
    if ftype is None:
        ftype = FacilityType(
            code="education_school",
            label="School / education facility",
            description="Education facility point as mapped in the source dataset.",
        )
        session.add(ftype)
        session.flush()

    units_gdf = gpd.read_postgis(
        "SELECT u.id, u.official_code, u.geometry FROM administrative_units u "
        "JOIN countries c ON c.id = u.country_id WHERE c.iso3 = 'SWZ' AND u.geometry IS NOT NULL",
        session.connection(),
        geom_col="geometry",
    )

    schools = gpd.read_file(bundle_dir / "raw" / "hotosm_swz_education_facilities_osm_geojson" / "education_facilities.geojson")
    if schools.crs is None or schools.crs.to_epsg() != 4326:
        schools = schools.to_crs(4326)

    joined = gpd.sjoin(schools, units_gdf, how="left", predicate="within")
    existing_ids = set(
        session.execute(select(Facility.source_facility_id).where(Facility.country_id == country.id)).scalars()
    )
    added = 0
    normalized = 0
    for i, row in joined.iterrows():
        name = str(row.get("school_name") or "").strip()
        source_fid = f"hotosm-swz-edu-{i}"
        if source_fid in existing_ids:
            continue
        unit_pk = row.get("id_right") if "id_right" in joined.columns else row.get("id")
        geom = row.geometry
        notes: dict = {
            "school_type": str(row.get("school_type") or "") or None,
            "data_source": "HOT OSM education facilities via HDX (crisis-baseline-kit v0.5.0)",
            "note": "Presence in OSM is not evidence of current operation.",
        }
        if geom.geom_type != "Point":
            # Some mapped schools are campus-area polygons; store the centroid
            # point and record the normalisation (documented transform).
            notes["geometry_normalisation"] = (
                f"source geometry was {geom.geom_type}; stored its centroid point"
            )
            geom = geom.centroid
            normalized += 1
        facility = Facility(
            country_id=country.id,
            facility_type_id=ftype.id,
            name=name if name and name.lower() != "nan" else "Unnamed education facility (as mapped)",
            operational_status=OperationalStatus.unknown,
            geometry=WKTElement(geom.wkt, srid=SRID),
            unit_id=str(unit_pk) if unit_pk is not None and not pd.isna(unit_pk) else None,
            source_id=sources["schools"].id,
            source_facility_id=source_fid,
            reference_date=sources["schools"].reference_date,
            properties=notes,
        )
        session.add(facility)
        stype = str(row.get("school_type") or "").strip()
        if stype and stype.lower() != "nan":
            session.add(FacilityService(facility=facility, service=stype))
        added += 1
    if normalized:
        print(f"  (normalised {normalized} polygon geometries to centroid points)")
    print(f"  education facilities added: {added}")


def run(bundle_dir: Path) -> None:
    print(f"Phase 1 seed using bundle: {bundle_dir}")
    with session_scope() as session:
        print("1. African country registry…")
        by_iso3 = seed_countries(session)
        print(f"   {len(by_iso3)} countries registered")

        print("2. Sources + data catalogue…")
        sources = register_sources_and_datasets(session, bundle_dir)
        print(f"   {len(sources)} sources registered")

        print("3. Eswatini boundaries…")
        country = by_iso3["SWZ"]
        country.status = CountryStatus.active
        ingest_swz_boundaries(session, country, bundle_dir, sources["codab"])

        print("4. Real indicator observations…")
        seed_indicators(session, country, bundle_dir, sources)

        print("5. Real education facilities…")
        seed_facilities(session, country, bundle_dir, sources)

    print("Phase 1 seed complete.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True,
                        help="extracted crisis-baseline-kit swz-baseline-* directory")
    args = parser.parse_args()
    run(args.bundle_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
