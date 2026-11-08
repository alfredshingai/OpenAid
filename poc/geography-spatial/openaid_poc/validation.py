"""Feature-level validation for geographic ingestion.

Pure functions: no database access. The ingestion layer combines these with
database lookups (duplicate codes, parent resolution).

Every rejection produces machine-readable ``reason_code``s plus a
human-actionable detail message — quarantined features must be diagnosable
without guesswork (blueprint §16).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import shapely
from shapely.geometry import shape as _shape
from shapely.geometry.base import BaseGeometry

ALLOWED_GEOMETRY_TYPES = {"Polygon", "MultiPolygon"}
SRID = 4326

# Machine-readable rejection reasons
R_MISSING_PROPERTY = "missing_property"
R_INVALID_PROPERTY = "invalid_property"
R_COUNTRY_MISMATCH = "country_mismatch"
R_UNKNOWN_LEVEL = "unknown_level"
R_DUPLICATE_CODE = "duplicate_code"
R_MISSING_PARENT = "missing_parent"
R_INVALID_PARENT_LEVEL = "invalid_parent_level"
R_UNSUPPORTED_CRS = "unsupported_crs"
R_UNSUPPORTED_GEOMETRY_TYPE = "unsupported_geometry_type"
R_INVALID_GEOMETRY = "invalid_geometry"
R_EMPTY_GEOMETRY = "empty_geometry"
R_OUT_OF_RANGE_COORDINATES = "out_of_range_coordinates"
R_MISSING_GEOMETRY = "missing_geometry"


@dataclass
class FeatureIssue:
    feature_index: int
    reason_codes: list[str]
    detail: str
    raw_properties: dict[str, Any] | None = None
    raw_geometry_wkt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_index": self.feature_index,
            "reason_codes": self.reason_codes,
            "detail": self.detail,
        }


@dataclass
class ParsedFeature:
    """A feature that passed structural + geometry validation."""

    feature_index: int
    name: str
    official_code: str
    admin_level: int
    parent_code: str | None
    source_unit_id: str | None
    properties: dict[str, Any]
    geometry: BaseGeometry
    normalized_from: str | None = None  # e.g. "Polygon->MultiPolygon"


@dataclass
class ValidationResult:
    features: list[ParsedFeature] = field(default_factory=list)
    issues: list[FeatureIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _iter_coordinates(geom: BaseGeometry):
    if geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        yield from geom.exterior.coords
        yield from (c for ring in geom.interiors for c in ring.coords)
    elif geom.geom_type == "MultiPolygon":
        for poly in geom.geoms:
            yield from poly.exterior.coords
            yield from (c for ring in poly.interiors for c in ring.coords)
    else:
        yield from geom.coords


def _coordinates_in_range(geom: BaseGeometry) -> bool:
    for x, y in _iter_coordinates(geom):
        if not (-180.0 <= float(x) <= 180.0 and -90.0 <= float(y) <= 90.0):
            return False
    return True


def _parse_geometry(feature_index: int, geometry: Any, result: ValidationResult) -> BaseGeometry | None:
    """Parse and geometrically validate one feature's geometry.

    Returns the validated (possibly normalised) geometry, or None once an
    issue has been appended for the feature.
    """
    if geometry is None:
        result.issues.append(
            FeatureIssue(feature_index, [R_MISSING_GEOMETRY], "feature has no geometry member")
        )
        return None

    try:
        geom = _shape(geometry) if isinstance(geometry, dict) else geometry
        if not isinstance(geom, BaseGeometry):
            raise TypeError(f"not a geometry object: {type(geom).__name__}")
    except Exception as exc:  # malformed structure
        result.issues.append(
            FeatureIssue(feature_index, [R_INVALID_GEOMETRY], f"could not parse geometry: {exc}")
        )
        return None

    if geom.is_empty:
        result.issues.append(
            FeatureIssue(feature_index, [R_EMPTY_GEOMETRY], "geometry is empty")
        )
        return None

    if geom.geom_type not in ALLOWED_GEOMETRY_TYPES:
        result.issues.append(
            FeatureIssue(
                feature_index,
                [R_UNSUPPORTED_GEOMETRY_TYPE],
                f"administrative boundaries must be Polygon or MultiPolygon, got {geom.geom_type}",
            )
        )
        return None

    if not _coordinates_in_range(geom):
        result.issues.append(
            FeatureIssue(
                feature_index,
                [R_OUT_OF_RANGE_COORDINATES],
                "coordinates outside lon[-180,180] / lat[-90,90] — wrong CRS or corrupt data?",
            )
        )
        return None

    normalized_from = None
    if geom.geom_type == "Polygon":
        geom = shapely.MultiPolygon([geom])
        normalized_from = "Polygon"
    if shapely.has_z(geom):
        geom = shapely.force_2d(geom)
        normalized_from = normalized_from or "3D geometry"

    if not geom.is_valid:
        from shapely.validation import explain_validity

        result.issues.append(
            FeatureIssue(
                feature_index,
                [R_INVALID_GEOMETRY],
                f"invalid geometry ({explain_validity(geom)}); fix the source, do not ship broken boundaries",
            )
        )
        return None

    if normalized_from:
        result.warnings.append(
            f"feature {feature_index}: normalised {normalized_from} to MultiPolygon (lossless)"
        )
    return geom


def validate_features(
    features: list[tuple[int, dict[str, Any], Any]],
    configured_levels: dict[int, str],
    expected_country_iso3: str,
    existing_codes: set[str],
    allow_existing: bool = False,
) -> ValidationResult:
    """Validate parsed features against the country's configuration.

    ``features`` is a list of ``(index, properties, geometry)`` tuples.
    ``configured_levels`` maps level_number -> level_name for the target
    country. ``existing_codes`` are official codes already stored for the
    country (duplicate detection). ``allow_existing`` (upsert mode) disables
    the duplicate-code rejection so existing units can receive a new
    boundary version instead.
    """
    result = ValidationResult()
    seen_codes: dict[str, int] = {}

    for index, properties, geometry in features:
        problems: list[tuple[str, str]] = []  # (reason_code, detail)

        props = properties if isinstance(properties, dict) else None
        if props is None:
            result.issues.append(
                FeatureIssue(index, [R_INVALID_PROPERTY], "properties member is missing or not an object")
            )
            continue

        raw_wkt = None
        try:
            g = _shape(geometry) if isinstance(geometry, dict) else geometry
            if isinstance(g, BaseGeometry):
                raw_wkt = g.wkt[:2000]
        except Exception:
            raw_wkt = None

        def issue(reasons: list[tuple[str, str]]) -> None:
            result.issues.append(
                FeatureIssue(
                    index,
                    [r for r, _ in reasons],
                    "; ".join(d for _, d in reasons),
                    raw_properties=props,
                    raw_geometry_wkt=raw_wkt,
                )
            )

        # --- property schema -------------------------------------------------
        name = props.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append((R_MISSING_PROPERTY, "'name' is required and must be a non-empty string"))

        official_code = props.get("official_code")
        if not isinstance(official_code, str) or not official_code.strip():
            problems.append(
                (R_MISSING_PROPERTY, "'official_code' is required and must be a non-empty string")
            )

        admin_level = props.get("admin_level")
        if isinstance(admin_level, str) and admin_level.isdigit():
            admin_level = int(admin_level)
        if not isinstance(admin_level, int) or isinstance(admin_level, bool) or admin_level < 1:
            problems.append(
                (R_MISSING_PROPERTY, "'admin_level' is required and must be a positive integer")
            )

        country_iso3 = props.get("country_iso3")
        if not isinstance(country_iso3, str) or not country_iso3.strip():
            problems.append((R_MISSING_PROPERTY, "'country_iso3' is required for country association"))
        elif expected_country_iso3 and country_iso3.upper() != expected_country_iso3.upper():
            problems.append(
                (
                    R_COUNTRY_MISMATCH,
                    f"feature declares country {country_iso3!r} but import targets {expected_country_iso3!r}",
                )
            )

        parent_code: str | None = props.get("parent_code")
        if isinstance(admin_level, int) and admin_level > 1:
            if not isinstance(parent_code, str) or not parent_code.strip():
                problems.append(
                    (R_MISSING_PROPERTY, f"'parent_code' is required for admin_level {admin_level} (> 1)")
                )

        source_unit_id = props.get("source_unit_id")
        if source_unit_id is not None and not isinstance(source_unit_id, str):
            problems.append((R_INVALID_PROPERTY, "'source_unit_id' must be a string when present"))

        if problems:
            issue(problems)
            continue

        assert isinstance(name, str) and isinstance(official_code, str)
        assert isinstance(admin_level, int)

        # --- level configuration --------------------------------------------
        if admin_level not in configured_levels:
            known = ", ".join(str(l) for l in sorted(configured_levels))
            result.issues.append(
                FeatureIssue(
                    index,
                    [R_UNKNOWN_LEVEL],
                    f"admin_level {admin_level} is not configured for {expected_country_iso3} (configured levels: {known})",
                    raw_properties=props,
                    raw_geometry_wkt=raw_wkt,
                )
            )
            continue

        # --- duplicates -------------------------------------------------------
        if official_code in seen_codes:
            result.issues.append(
                FeatureIssue(
                    index,
                    [R_DUPLICATE_CODE],
                    f"official_code {official_code!r} appears twice in the file (first at feature {seen_codes[official_code]})",
                    raw_properties=props,
                    raw_geometry_wkt=raw_wkt,
                )
            )
            continue
        if official_code in existing_codes and not allow_existing:
            result.issues.append(
                FeatureIssue(
                    index,
                    [R_DUPLICATE_CODE],
                    f"official_code {official_code!r} already exists in the database for {expected_country_iso3} "
                    "(use upsert mode to add a new boundary version)",
                )
            )
            continue
        seen_codes[official_code] = index

        # --- geometry ---------------------------------------------------------
        geom = _parse_geometry(index, geometry, result)
        if geom is None:
            continue

        result.features.append(
            ParsedFeature(
                feature_index=index,
                name=name.strip(),
                official_code=official_code.strip(),
                admin_level=admin_level,
                parent_code=parent_code.strip() if isinstance(parent_code, str) else None,
                source_unit_id=source_unit_id if isinstance(source_unit_id, str) else None,
                properties=props,
                geometry=geom,
            )
        )

    return result


def resolve_parents(
    features: list[ParsedFeature],
    db_parents: dict[str, tuple[int, Any]],
) -> list[FeatureIssue]:
    """Cross-feature integrity: parents must resolve and sit one level above.

    ``db_parents`` maps official_code -> (level_number, unit_id) for units
    already stored for the country. Returns issues (no mutation).
    """
    code_to_level: dict[str, int] = {f.official_code: f.admin_level for f in features}
    issues: list[FeatureIssue] = []

    for f in features:
        if f.admin_level == 1:
            continue
        assert f.parent_code is not None  # guaranteed by validate_features
        if f.parent_code in code_to_level:
            parent_level = code_to_level[f.parent_code]
        elif f.parent_code in db_parents:
            parent_level = db_parents[f.parent_code][0]
        else:
            issues.append(
                FeatureIssue(
                    f.feature_index,
                    [R_MISSING_PARENT],
                    f"parent_code {f.parent_code!r} not found in file or database for {f.official_code!r}",
                    raw_properties=f.properties,
                )
            )
            continue
        if parent_level != f.admin_level - 1:
            issues.append(
                FeatureIssue(
                    f.feature_index,
                    [R_INVALID_PARENT_LEVEL],
                    f"parent {f.parent_code!r} of {f.official_code!r} is level {parent_level}, "
                    f"but must be level {f.admin_level - 1}",
                    raw_properties=f.properties,
                )
            )
    return issues
