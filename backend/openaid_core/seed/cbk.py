"""Generic crisis-baseline-kit bundle onboarding.

Onboards any country from a cbk release bundle (OCHA COD-AB boundaries via
HDX + WorldPop population + OSM-derived statistics), driven entirely by a
per-country profile: no country-specific code paths. This is the
operational version of the PoC's "onboard a country by data + configuration"
property.

Provenance recorded per run: bundle manifest (source URLs, licences,
retrieval dates, raw-file SHA-256), all attributed on the data source rows
and the data-catalogue entries.

Usage:
    python -m openaid_core.seed.cbk --bundle-dir <extracted bundle> --country KEN
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
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


@dataclass
class CountryProfile:
    """Everything the onboarding workflow needs to know about a country.

    Identity fields may be None for generic onboarding (batch): the existing
    country row (name/region from the African registry) is kept and only the
    hierarchy + data are onboarded. Local terminology stays unclaimed until
    a human confirms it.
    """

    iso2: str | None
    iso3: str
    name: str | None
    official_name: str | None
    capital: str | None
    region: str | None
    languages: list[str] | None
    currency: str | None
    timezone: str | None
    # level_number -> (local level name, description)
    levels: dict[int, tuple[str, str]]
    facility_type_code: str = "education_school"
    facility_type_label: str = "School / education facility"
    facility_type_description: str = "Education facility point as mapped in the source dataset."
    extra_indicators: list[dict] = field(default_factory=list)


PROFILES: dict[str, CountryProfile] = {
    "SWZ": CountryProfile(
        iso2="SZ",
        iso3="SWZ",
        name="Eswatini",
        official_name="Kingdom of Eswatini",
        capital="Mbabane (executive), Lobamba (legislative, royal)",
        region="Southern Africa",
        languages=["English", "siSwati"],
        currency="SZL (Eswatini Lilangeni)",
        timezone="Africa/Mbabane (UTC+02:00)",
        levels={
            1: ("Region (admin-1)", "Eswatini first-level divisions (4); local terminology "
                "confirmation is part of full country onboarding review."),
            2: ("Tinkhundla (admin-2)", "Eswatini second-level divisions (55 tinkhundla)."),
        },
    ),
    "KEN": CountryProfile(
        iso2="KE",
        iso3="KEN",
        name="Kenya",
        official_name="Republic of Kenya",
        capital="Nairobi",
        region="Eastern Africa",
        languages=["English", "Kiswahili"],
        currency="KES (Kenyan Shilling)",
        timezone="Africa/Nairobi (UTC+03:00)",
        levels={
            1: ("County (admin-1)", "Kenya's 47 counties (IEBC boundaries via OCHA COD-AB)."),
            2: ("Sub-County (admin-2)", "Kenya's 290 sub-counties (IEBC boundaries via OCHA COD-AB)."),
        },
        extra_indicators=[
            {
                "code": "health_facilities_count",
                "name": "Health facilities (mapped)",
                "category": IndicatorCategory.health,
                "unit": "facilities",
                "measurement_type": MeasurementType.count,
                "aggregation_method": AggregationMethod.sum,
                "description": "Number of health facility points mapped in the "
                "source dataset within the geography.",
                "methodology": "Count of healthsites.io facility points (via HDX) "
                "inside the unit boundary. Counts reflect mapping coverage, not "
                "the true number or operational status of facilities.",
            },
        ],
    ),
}

# Indicator definitions shared by every onboarding (values come from recorded
# sources only; definitions are factual).
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
        "methodology": "Count of education facility points from the recorded "
        "source inside the unit boundary. Counts reflect mapping coverage, "
        "not the true number or operational status of facilities.",
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


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def register_country(session, profile: CountryProfile) -> Country:
    """Create (or complete) the country row, hierarchy and configuration."""
    country = session.execute(select(Country).where(Country.iso3 == profile.iso3)).scalar_one_or_none()
    if country is None:
        country = Country(
            iso2=profile.iso2, iso3=profile.iso3, name=profile.name,
            official_name=profile.official_name, capital=profile.capital,
            region=profile.region, status=CountryStatus.placeholder,
        )
        session.add(country)
        session.flush()
    country.status = CountryStatus.active
    for number, (name, desc) in profile.levels.items():
        exists = session.execute(
            select(AdministrativeLevel).where(
                AdministrativeLevel.country_id == country.id,
                AdministrativeLevel.level_number == number,
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(AdministrativeLevel(country_id=country.id, level_number=number,
                                            level_name=name, description=desc))
    config = session.execute(
        select(CountryConfiguration).where(CountryConfiguration.country_id == country.id)
    ).scalar_one_or_none()
    if config is None:
        session.add(
            CountryConfiguration(
                country_id=country.id,
                languages=profile.languages,
                currency=profile.currency,
                timezone=profile.timezone,
                configuration={"onboarding": "crisis-baseline-kit v0.5.0 bundle"},
            )
        )
    session.flush()
    return country


def register_sources_and_datasets(session, bundle_dir: Path, profile: CountryProfile) -> dict[str, DataSource]:
    """Source registry + catalogue rows built from the bundle manifest."""
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    layers = {l["layer"]: l for l in manifest["layers"]}
    admin = layers["admin_boundaries"]
    population = layers.get("population", {})
    roads = layers.get("roads", {})
    schools = layers.get("schools", {})

    def _src(key: str, name: str, **kw) -> DataSource:
        src = session.execute(select(DataSource).where(DataSource.name == name)).scalar_one_or_none()
        if src is None:
            src = DataSource(name=name, **kw)
            session.add(src)
            session.flush()
        return src

    iso = profile.iso3.lower()
    sources = {
        "codab": _src(
            "codab", f"OCHA COD-AB {profile.name} (via crisis-baseline-kit v0.5.0)",
            type="national administrative boundaries",
            publisher="National statistics/authoritative source via OCHA HDX; packaged by crisis-baseline-kit",
            url=admin["source_urls"][0],
            licence="CC BY-IGO (Creative Commons Attribution 4.0 for Intergovernmental Organisations)",
            attribution=admin["attribution"],
            reference_date=_date(str(admin.get("source_version", ""))[:10]),
            metadata_={
                "retrieved_at": admin.get("retrieved_at"),
                "source_version": admin.get("source_version"),
                "raw_files_sha256": {f["name"]: f["sha256"] for f in admin.get("raw_files", [])},
                "bundle_url": _bundle_url(profile.iso3),
            },
        ),
        "worldpop": _src(
            "worldpop", f"WorldPop 2020 constrained population ({profile.iso3})",
            type="gridded population model",
            publisher="WorldPop, University of Southampton; packaged by crisis-baseline-kit",
            url="https://hub.worldpop.org/",
            licence="CC-BY 4.0",
            attribution=population.get("attribution", f"WorldPop ({profile.iso3} 2020, ppp, 100 m)"),
            reference_date=date(2020, 12, 31),
            metadata_={"retrieved_at": population.get("retrieved_at"), "bundle_url": _bundle_url(profile.iso3)},
        ),
        "schools": _src(
            "schools", f"HOT OSM education facilities {profile.name} (via HDX)",
            type="facility points",
            publisher="Humanitarian OpenStreetMap Team via HDX; packaged by crisis-baseline-kit",
            url=schools.get("source_urls", ["https://data.humdata.org/"])[0],
            licence="Open Database License (ODC-ODbL)",
            attribution=schools.get("attribution", "HOT OSM education facilities"),
            metadata_={"retrieved_at": schools.get("retrieved_at"), "bundle_url": _bundle_url(profile.iso3)},
        ),
        "roads": _src(
            "roads", f"OSM roads {profile.name} (via Geofabrik)",
            type="road network",
            publisher="OpenStreetMap contributors via Geofabrik; packaged by crisis-baseline-kit",
            url=roads.get("source_urls", ["https://download.geofabrik.de/africa.html"])[0],
            licence="ODbL",
            attribution="OpenStreetMap contributors",
            metadata_={"retrieved_at": roads.get("retrieved_at"), "bundle_url": _bundle_url(profile.iso3)},
        ),
    }

    catalogue = [
        (
            f"ocha-codab-{iso}-admin-boundaries",
            f"{profile.name} Administrative Boundaries (COD-AB)",
            f"Official administrative boundaries from the national authoritative "
            f"source via OCHA HDX, packaged by crisis-baseline-kit v0.5.0: "
            + "; ".join(f"admin-{n} {name.split(' (')[0]}s" for n, (name, _d) in sorted(profile.levels.items())) + ".",
            "codab", str(admin.get("source_version", ""))[:10],
        ),
        (
            f"worldpop-2020-{iso}-population",
            f"{profile.name} Population 2020 (WorldPop 100 m)",
            "Modelled gridded population (WorldPop 2020 constrained, 100 m) "
            "summarised per administrative unit by crisis-baseline-kit.",
            "worldpop", "2020-12-31",
        ),
        (
            f"hot-osm-education-facilities-{iso}",
            f"{profile.name} Education Facilities (HOT OSM via HDX)",
            "Education facility points mapped by the OSM community; counts "
            "reflect mapping coverage and imply nothing about operational "
            "status.",
            "schools", None,
        ),
        (
            f"osm-roads-{iso}",
            f"{profile.name} Road Network (OSM via Geofabrik)",
            "Road network lines from OpenStreetMap; length statistics per "
            "administrative unit computed by crisis-baseline-kit.",
            "roads", None,
        ),
    ]
    for slug, title, desc, src_key, ref in catalogue:
        ds = session.execute(select(Dataset).where(Dataset.slug == slug)).scalar_one_or_none()
        if ds is None:
            ds = Dataset(
                slug=slug, title=title, description=desc,
                publisher=sources[src_key].publisher,
                licence=sources[src_key].licence,
                attribution=sources[src_key].attribution,
                access_class=AccessClass.public,
                language="en",
                spatial_coverage={"countries": [profile.iso3],
                                  "levels": [f"admin{n}" for n in sorted(profile.levels)]},
                temporal_coverage={"start": ref} if ref else None,
                homepage_url=_bundle_url(profile.iso3),
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
                for n in sorted(profile.levels):
                    ds.files.append(DatasetFile(filename="cbk_baseline.gpkg", format="gpkg", layer=f"admin{n}"))
            elif src_key == "schools":
                ds.files.append(DatasetFile(filename="schools.parquet", format="parquet"))
            elif src_key == "roads":
                ds.files.append(DatasetFile(filename="roads.parquet", format="parquet"))
            else:
                ds.files.append(DatasetFile(filename="admin2.parquet", format="parquet"))
    return sources


def _bundle_url(iso3: str) -> str:
    return (
        "https://github.com/alfredshingai/crisis-baseline-kit/releases/download/"
        f"v0.5.0/{iso3.lower()}-baseline-2026-11-01.zip"
    )


def _contract_feature(props: dict, geometry: dict, admin_level: int, iso3: str) -> dict:
    if admin_level == 1:
        code, name, parent = props["adm1_pcode"], props["adm1_name"], None
    else:
        code, name, parent = props["adm2_pcode"], props["adm2_name"], props.get("adm1_pcode")
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "country_iso3": iso3,
            "official_code": code,
            "source_unit_id": code,
            "name": name,
            "admin_level": admin_level,
            "parent_code": parent,
            "codab": dict(props),
        },
    }


def ingest_boundaries(session, country: Country, bundle_dir: Path, source: DataSource,
                      profile: CountryProfile) -> None:
    """COD-AB boundaries: admin-1 via GeoJSON, admin-2 via GeoPackage."""
    configured = {n: name for n, (name, _d) in profile.levels.items()}

    admin1 = json.loads((bundle_dir / "data" / "admin1.geojson").read_text(encoding="utf-8"))
    features1 = [_contract_feature(f["properties"], f["geometry"], 1, profile.iso3) for f in admin1["features"]]
    meta = ImportMeta(
        country_id=country.id, country_iso3=country.iso3, configured_levels=configured,
        source=source, reference_date=source.reference_date,
        filename="admin1.geojson (COD-AB)", format=ImportFormat.geojson,
    )
    _b, report = ingest_geojson_bytes(
        session, meta, json.dumps({"type": "FeatureCollection", "features": features1}).encode()
    )
    print(f"  admin1 boundaries: {report.status.value} imported={report.imported} quarantined={report.quarantined}")

    layers_available = {layer for layer, _geom in pyogrio.list_layers(bundle_dir / "cbk_baseline.gpkg")}
    if "admin2" not in layers_available:
        print("  admin2 boundaries: layer not present in this bundle — admin-1 only country")
        return
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
    source_crs = gdf.crs if gdf.crs is not None else "EPSG:4326"
    contract = gpd.GeoDataFrame(pd.DataFrame(records), geometry=gdf.geometry.values, crs=source_crs)
    with tempfile.TemporaryDirectory(prefix="openaid_seed_") as tmp:
        tmp_gpkg = Path(tmp) / f"{profile.iso3.lower()}_admin2_contract.gpkg"
        contract.to_file(tmp_gpkg, layer="admin2", driver="GPKG")
        meta2 = ImportMeta(
            country_id=country.id, country_iso3=country.iso3, configured_levels=configured,
            source=source, reference_date=source.reference_date,
            filename="cbk_baseline.gpkg:admin2 (contract-converted)", format=ImportFormat.gpkg,
        )
        _b, report = ingest_gpkg_file(session, meta2, tmp_gpkg, layer="admin2")
    print(f"  admin2 boundaries: {report.status.value} imported={report.imported} quarantined={report.quarantined}")


def _indicator_defs(session, profile: CountryProfile) -> dict[str, IndicatorDefinition]:
    defs: dict[str, IndicatorDefinition] = {}
    for spec in INDICATOR_DEFS + profile.extra_indicators:
        d = session.execute(
            select(IndicatorDefinition).where(IndicatorDefinition.code == spec["code"])
        ).scalar_one_or_none()
        if d is None:
            d = IndicatorDefinition(**spec)
            session.add(d)
            session.flush()
        defs[spec["code"]] = d
    return defs


def seed_indicators(session, country: Country, bundle_dir: Path, sources: dict[str, DataSource],
                    profile: CountryProfile) -> None:
    """Per-unit observations from the bundle's admin2 statistics table."""
    defs = _indicator_defs(session, profile)
    units: dict[str, AdministrativeUnit] = {
        u.official_code: u
        for u in session.execute(
            select(AdministrativeUnit).where(AdministrativeUnit.country_id == country.id)
        ).scalars().all()
    }

    # Deepest available stats table: admin-1-only countries (e.g. ESH, STP)
    # ship admin1.parquet instead of admin2.parquet.
    stats_path = bundle_dir / "admin2.parquet"
    if not stats_path.exists():
        stats_path = bundle_dir / "admin1.parquet"
    if not stats_path.exists():
        print("  indicator observations: no stats table in bundle — skipped")
        return
    df = pd.read_parquet(stats_path)
    is_admin2 = "adm2_pcode" in df.columns
    code_col = "adm2_pcode" if is_admin2 else "adm1_pcode"
    parent_col = "adm1_pcode" if is_admin2 else None
    # Dedupe key includes country: country-level rows (unit_id NULL) would
    # otherwise collide across countries.
    existing = {
        (str(c), str(u), str(d))
        for c, u, d in session.execute(
            select(
                IndicatorObservation.country_id,
                IndicatorObservation.unit_id,
                IndicatorObservation.indicator_definition_id,
            )
        ).all()
    }
    added = 0

    def _add(unit: AdministrativeUnit | None, code: str, value, value_type: ValueType,
             src, version: str, period: date, notes: str | None = None) -> None:
        nonlocal added
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return
        d = defs[code]
        unit_id = unit.id if unit is not None else None
        if (str(country.id), str(unit_id), str(d.id)) in existing:
            return
        session.add(
            IndicatorObservation(
                country_id=country.id, unit_id=unit_id, indicator_definition_id=d.id,
                period_start=period, period_end=period,
                value=float(value), value_type=value_type,
                source_id=src.id, dataset_version=version, methodology_notes=notes,
            )
        )
        added += 1

    period = date(2020, 12, 31)
    pop_src, school_src, road_src = sources["worldpop"], sources["schools"], sources["roads"]

    admin1_pop: dict[str, float] = {}
    admin1_schools: dict[str, float] = {}
    admin1_health: dict[str, float] = {}
    country_pop = 0.0
    country_schools = 0.0
    country_health = 0.0
    has_health = "facility_count" in df.columns and "health_facilities_count" in defs

    for _, row in df.iterrows():
        unit = units.get(str(row[code_col]))
        if unit is None:
            continue
        pop = row.get("population_sum")
        _add(unit, "total_population", pop, ValueType.modelled, pop_src, "worldpop-2020-100m",
             period, "WorldPop 2020 zonal sum (modelled gridded population).")
        _add(unit, "population_density", row.get("pop_density_km2"), ValueType.modelled, pop_src,
             "worldpop-2020-100m", period, "WorldPop population / unit area (source-derived).")
        schools = row.get("school_count")
        _add(unit, "education_facilities_count", schools, ValueType.observed, school_src,
             "hdx-hotosm-2026-11", period,
             "Count of mapped education facility points; reflects mapping coverage.")
        _add(unit, "schools_per_10k_population", row.get("schools_per_10k_pop"), ValueType.observed,
             school_src, "hdx-hotosm-2026-11", period,
             "Facility count per 10k WorldPop population; mapping coverage metric.")
        _add(unit, "road_density", row.get("road_km_per_100km2"), ValueType.observed, road_src,
             "geofabrik-2026", period, "OSM road km per 100 km2; reflects OSM mapping coverage.")
        if has_health:
            health = row.get("facility_count")
            _add(unit, "health_facilities_count", health, ValueType.observed, school_src,
                 "hdx-healthsites-2026-11", period,
                 "Count of mapped health facility points (healthsites.io); mapping coverage.")
            if health is not None and not pd.isna(health):
                if parent_col:
                    p1 = str(row[parent_col])
                    admin1_health[p1] = admin1_health.get(p1, 0.0) + float(health)
                country_health += float(health)
        if pop is not None and not pd.isna(pop):
            if parent_col:
                p1 = str(row[parent_col])
                admin1_pop[p1] = admin1_pop.get(p1, 0.0) + float(pop)
            country_pop += float(pop)
        if schools is not None and not pd.isna(schools):
            if parent_col:
                p1 = str(row[parent_col])
                admin1_schools[p1] = admin1_schools.get(p1, 0.0) + float(schools)
            country_schools += float(schools)

    # Summable indicators only — rate metrics are NOT aggregated.
    for pcode, total in admin1_pop.items():
        _add(units.get(pcode), "total_population", total, ValueType.modelled, pop_src,
             "worldpop-2020-100m", period, "Sum of admin-2 WorldPop zonal sums for this unit.")
    for pcode, total in admin1_schools.items():
        _add(units.get(pcode), "education_facilities_count", total, ValueType.observed, school_src,
             "hdx-hotosm-2026-11", period, "Sum of admin-2 mapped facility counts.")
    if has_health:
        for pcode, total in admin1_health.items():
            _add(units.get(pcode), "health_facilities_count", total, ValueType.observed, school_src,
                 "hdx-healthsites-2026-11", period, "Sum of admin-2 mapped facility counts.")
    if country_pop:
        _add(None, "total_population", country_pop, ValueType.modelled, pop_src,
             "worldpop-2020-100m", period, "Country total: sum of admin-2 WorldPop zonal sums.")
    if country_schools:
        _add(None, "education_facilities_count", country_schools, ValueType.observed, school_src,
             "hdx-hotosm-2026-11", period, "Country total: sum of admin-2 mapped facility counts.")
    if has_health and country_health:
        _add(None, "health_facilities_count", country_health, ValueType.observed, school_src,
             "hdx-healthsites-2026-11", period, "Country total: sum of admin-2 mapped facility counts.")

    print(f"  indicator observations added: {added}")


def seed_facilities(session, country: Country, bundle_dir: Path, sources: dict[str, DataSource],
                    profile: CountryProfile) -> None:
    """Facility points from the bundle's schools layer, assigned to units."""
    ftype = session.execute(
        select(FacilityType).where(FacilityType.code == profile.facility_type_code)
    ).scalar_one_or_none()
    if ftype is None:
        ftype = FacilityType(
            code=profile.facility_type_code, label=profile.facility_type_label,
            description=profile.facility_type_description,
        )
        session.add(ftype)
        session.flush()

    # country.id is a server-generated UUID (never user input), so inlining
    # is safe; pandas' driver-level SQL does not accept bind params here.
    units_gdf = gpd.read_postgis(
        f"SELECT u.id, u.official_code, u.geometry FROM administrative_units u "
        f"WHERE u.country_id = '{country.id}' AND u.geometry IS NOT NULL",
        session.connection(),
        geom_col="geometry",
    )

    schools_path = bundle_dir / "data" / "schools.geojson"
    if not schools_path.exists():
        print("  education facilities: no schools layer in bundle — skipped")
        return
    schools = gpd.read_file(schools_path)
    if schools.crs is None or schools.crs.to_epsg() != 4326:
        schools = schools.to_crs(4326)
    schools = schools.reset_index(drop=True)  # feature index = stable identity

    # A school touching more than one unit polygon yields several joined rows;
    # keep one facility per source feature (first unit match wins).
    joined = gpd.sjoin(schools, units_gdf, how="left", predicate="within").reset_index()
    joined = joined.drop_duplicates(subset="index")
    existing_ids = set(
        session.execute(select(Facility.source_facility_id).where(Facility.country_id == country.id)).scalars()
    )
    added = normalized = 0
    for i, row in joined.iterrows():
        name = str(row.get("school_name") or "").strip()
        source_fid = f"cbk-{profile.iso3.lower()}-school-{row['index']}"
        if source_fid in existing_ids:
            continue
        unit_pk = row.get("id_right") if "id_right" in joined.columns else row.get("id")
        geom = row.geometry
        notes: dict = {
            "school_type": str(row.get("school_type") or "") or None,
            "data_source": sources["schools"].name,
            "note": "Presence in the source dataset is not evidence of current operation.",
        }
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type != "Point":
            notes["geometry_normalisation"] = (
                f"source geometry was {geom.geom_type}; stored its centroid point"
            )
            geom = geom.centroid
            normalized += 1
        session.add(
            Facility(
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
                # FacilityService rows need the facility id -> flush per row
                services=[FacilityService(service=stype)]
                if (stype := str(row.get("school_type") or "").strip()) and stype.lower() != "nan"
                else [],
            )
        )
        added += 1
        if added % 2000 == 0:
            session.flush()
    if normalized:
        print(f"  (normalised {normalized} polygon geometries to centroid points)")
    print(f"  education facilities added: {added}")


def onboard(bundle_dir: Path, iso3: str) -> None:
    profile = PROFILES.get(iso3.upper())
    if profile is None:
        raise SystemExit(f"no profile for {iso3}; add one to openaid_core.seed.cbk.PROFILES")
    _onboard_with_profile(bundle_dir, profile)


def _onboard_with_profile(bundle_dir: Path, profile: CountryProfile) -> None:
    print(f"Onboarding {profile.name or profile.iso3} ({profile.iso3}) from {bundle_dir}")
    with session_scope() as session:
        country = register_country(session, profile)
        print("  country registered/activated")
        sources = register_sources_and_datasets(session, bundle_dir, profile)
        print(f"  {len(sources)} sources + catalogue entries")
        ingest_boundaries(session, country, bundle_dir, sources["codab"], profile)
        seed_indicators(session, country, bundle_dir, sources, profile)
        seed_facilities(session, country, bundle_dir, sources, profile)
    print(f"Onboarding {profile.iso3} complete.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--country", required=True, help="ISO3 key in PROFILES (e.g. KEN)")
    args = parser.parse_args()
    onboard(args.bundle_dir.resolve(), args.country)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
