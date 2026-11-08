"""Review→publish pipeline: apply approved submissions as versioned changes.

Approval is not just a status flip — each submission type has a concrete,
validated application step that runs inside the reviewer's transaction:

* ``facility_correction``  → whitelisted fields updated on the facility,
  verification raised to ``verified``.
* ``boundary_correction``  → a NEW boundary version (history preserved) via
  the same append-only versioning as imports; unit marked ``verified``.
* ``organisation_new``     → organisation row created, ``verified``.
* ``dataset_new``          → catalogue row created.

If application fails validation, the reviewer gets a 422 and the submission
stays pending — nothing is half-applied.
"""

from __future__ import annotations

import uuid
from datetime import date

import shapely
from geoalchemy2 import WKTElement
from shapely.geometry import shape as _shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import SRID
from ..datasets.models import AccessClass, Dataset
from ..facilities.models import Facility, OperationalStatus
from ..geography.models import AdministrativeUnit, BoundaryVersion, Country
from ..geography.models import VerificationStatus as VS
from ..organisations.models import Organisation, OrganisationType
from .models import Submission, SubmissionType, User

FACILITY_FIELDS = {"name": str, "operational_status": OperationalStatus}


class ApplicationError(ValueError):
    """Raised when an approved submission cannot be applied; rolls everything back."""


def _get_payload(submission: Submission, key: str) -> object:
    value = (submission.payload or {}).get(key)
    if value is None:
        raise ApplicationError(f"submission payload missing '{key}'")
    return value


def _facility_for(session: Session, submission: Submission) -> Facility:
    facility_id = submission.payload.get("facility_id")
    if facility_id:
        facility = session.execute(
            select(Facility).where(Facility.id == uuid.UUID(str(facility_id)))
        ).scalar_one_or_none()
        if facility is None:
            raise ApplicationError(f"facility {facility_id} not found")
        return facility
    source_fid = submission.payload.get("source_facility_id")
    if source_fid:
        facility = session.execute(
            select(Facility).where(Facility.source_facility_id == str(source_fid))
        ).scalar_one_or_none()
        if facility is None:
            raise ApplicationError(f"facility with source id {source_fid} not found")
        return facility
    raise ApplicationError("payload needs 'facility_id' or 'source_facility_id'")


def _apply_facility_correction(session: Session, submission: Submission) -> dict:
    facility = _facility_for(session, submission)
    changes = submission.payload.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise ApplicationError("payload needs a non-empty 'changes' object")
    applied = {}
    for field, value in changes.items():
        if field not in FACILITY_FIELDS:
            raise ApplicationError(
                f"field '{field}' is not correctable; allowed: {sorted(FACILITY_FIELDS)}"
            )
        if field == "name":
            if not isinstance(value, str) or not value.strip():
                raise ApplicationError("'name' must be a non-empty string")
            facility.name = value.strip()
        elif field == "operational_status":
            try:
                facility.operational_status = OperationalStatus(str(value))
            except ValueError:
                raise ApplicationError(
                    f"invalid operational_status {value!r}; allowed: "
                    f"{[s.value for s in OperationalStatus]}"
                ) from None
        applied[field] = value
    facility.verification_status = VS.verified
    return {"facility_id": str(facility.id), "applied": applied}


def _apply_boundary_correction(session: Session, submission: Submission) -> dict:
    country_iso3 = str(_get_payload(submission, "country_iso3")).upper()
    official_code = str(_get_payload(submission, "official_code"))
    geometry = submission.payload.get("geometry")
    if not isinstance(geometry, dict):
        raise ApplicationError("payload needs a 'geometry' GeoJSON object")

    country = session.execute(select(Country).where(Country.iso3 == country_iso3)).scalar_one_or_none()
    if country is None:
        raise ApplicationError(f"country {country_iso3} not found")
    unit = session.execute(
        select(AdministrativeUnit).where(
            AdministrativeUnit.country_id == country.id,
            AdministrativeUnit.official_code == official_code,
        )
    ).scalar_one_or_none()
    if unit is None:
        raise ApplicationError(f"unit {official_code} not found in {country_iso3}")

    try:
        geom = _shape(geometry)
    except Exception as exc:
        raise ApplicationError(f"geometry not parseable: {exc}") from None
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ApplicationError(f"boundary must be Polygon/MultiPolygon, got {geom.geom_type}")
    if geom.is_empty or not geom.is_valid:
        raise ApplicationError(f"geometry invalid ({geom.is_valid=}, empty={geom.is_empty}); fix the source")
    if geom.geom_type == "Polygon":
        geom = shapely.MultiPolygon([geom])
    minx, miny, maxx, maxy = geom.bounds
    if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
        raise ApplicationError("coordinates outside lon/lat range — wrong CRS?")

    reference = submission.payload.get("reference_date")
    reference_date = date.fromisoformat(str(reference)) if reference else date.today()
    if unit.reference_date and reference_date < unit.reference_date:
        raise ApplicationError(
            f"reference_date {reference_date} predates the current boundary ({unit.reference_date})"
        )

    current_version = session.execute(
        select(BoundaryVersion.version)
        .where(BoundaryVersion.unit_id == unit.id)
        .order_by(BoundaryVersion.version.desc())
        .limit(1)
    ).scalar_one()
    # Close the open version, append the new one — history never overwritten.
    for version_row in session.execute(
        select(BoundaryVersion).where(
            BoundaryVersion.unit_id == unit.id, BoundaryVersion.valid_to.is_(None)
        )
    ).scalars():
        version_row.valid_to = reference_date
    next_version = int(current_version) + 1
    wkt = WKTElement(geom.wkt, srid=SRID)
    session.add(
        BoundaryVersion(
            unit_id=unit.id,
            version=next_version,
            geometry=wkt,
            valid_from=reference_date,
            valid_to=None,
        )
    )
    unit.geometry = WKTElement(geom.wkt, srid=SRID)
    unit.verification_status = VS.verified
    unit.reference_date = reference_date
    return {"unit": official_code, "new_version": next_version}


def _apply_organisation_new(session: Session, submission: Submission) -> dict:
    payload = submission.payload or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ApplicationError("'name' is required")
    try:
        org_type = OrganisationType(str(payload.get("org_type") or "other"))
    except ValueError:
        raise ApplicationError(
            f"invalid org_type; allowed: {[t.value for t in OrganisationType]}"
        ) from None
    org = Organisation(
        name=name,
        acronym=payload.get("acronym"),
        org_type=org_type,
        description=payload.get("description"),
        website=payload.get("website"),
        verification_status=VS.verified,
    )
    session.add(org)
    session.flush()
    return {"organisation_id": str(org.id), "name": name}


def _apply_dataset_new(session: Session, submission: Submission) -> dict:
    payload = submission.payload or {}
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ApplicationError("'title' is required")
    slug = str(payload.get("slug") or "").strip()
    if not slug:
        raise ApplicationError("'slug' is required")
    exists = session.execute(select(Dataset).where(Dataset.slug == slug)).scalar_one_or_none()
    if exists:
        raise ApplicationError(f"dataset slug '{slug}' already exists")
    try:
        access = AccessClass(str(payload.get("access_class") or "public"))
    except ValueError:
        raise ApplicationError(
            f"invalid access_class; allowed: {[a.value for a in AccessClass]}"
        ) from None
    ds = Dataset(
        slug=slug,
        title=title,
        description=payload.get("description"),
        publisher=payload.get("publisher"),
        licence=payload.get("licence"),
        attribution=payload.get("attribution"),
        access_class=access,
        is_synthetic=False,
    )
    session.add(ds)
    session.flush()
    return {"dataset_id": str(ds.id), "slug": slug}


_APPLIERS = {
    SubmissionType.facility_correction: _apply_facility_correction,
    SubmissionType.boundary_correction: _apply_boundary_correction,
    SubmissionType.organisation_new: _apply_organisation_new,
    SubmissionType.dataset_new: _apply_dataset_new,
}


def apply_submission(session: Session, submission: Submission) -> dict:
    """Apply an approved submission; raises ApplicationError on any problem."""
    if submission.submission_type not in _APPLIERS:
        raise ApplicationError(
            f"submission type '{submission.submission_type}' is recorded but has no "
            "application step yet (only corrections and new records apply automatically)"
        )
    return _APPLIERS[submission.submission_type](session, submission)
