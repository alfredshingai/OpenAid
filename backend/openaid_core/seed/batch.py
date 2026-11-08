"""Batch onboarding: every crisis-baseline-kit release country, idempotently.

Downloads each country bundle from the cbk v0.5.0 release, extracts it and
runs the generic onboarding (COD-AB boundaries → per-unit indicator
observations → facility points → sources → catalogue). Countries already
active with units are skipped, so re-runs resume where they stopped.

Level names for batch countries are deliberately generic ("Admin 1" /
"Admin 2") with descriptions marking local terminology as pending human
confirmation — the accuracy-before-appearance principle applied to
continental scale. Hand-written profiles (SWZ, KEN) keep their specific
labels.

Usage:
    python -m openaid_core.seed.batch                # all missing countries
    python -m openaid_core.seed.batch --only MOZ,ZWE # subset
    python -m openaid_core.seed.batch --list         # show plan, do nothing
"""

from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from pathlib import Path

import urllib.request

from sqlalchemy import select

from ..db import session_scope
from ..geography.models import AdministrativeUnit, Country, CountryStatus
from .cbk import PROFILES, CountryProfile, _onboard_with_profile

RELEASE_API = (
    "https://api.github.com/repos/alfredshingai/crisis-baseline-kit/releases/latest"
)
BUNDLE_ROOT = Path(__file__).resolve().parents[3] / ".cbk_cache"
ASSET_RE = re.compile(r"^([a-z]{3})-baseline-(.+)\.zip$")

GENERIC_LEVELS = {
    1: ("Admin 1", "First-level administrative divisions from OCHA COD-AB; local "
        "terminology pending confirmation during country onboarding review."),
    2: ("Admin 2", "Second-level administrative divisions from OCHA COD-AB; local "
        "terminology pending confirmation during country onboarding review."),
}


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "openaid-onboarding"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def release_assets() -> list[tuple[str, str, str]]:
    """[(iso3, version_tag, download_url)] for every country bundle."""
    data = json.loads(_fetch(RELEASE_API))
    out = []
    for asset in data.get("assets", []):
        match = ASSET_RE.match(asset["name"])
        if match:
            out.append((match.group(1).upper(), data["tag_name"], asset["browser_download_url"]))
    return sorted(out)


def onboarded_iso3s() -> set[str]:
    """Countries already active with at least one unit."""
    with session_scope() as session:
        rows = session.execute(
            select(Country.iso3)
            .join(AdministrativeUnit, AdministrativeUnit.country_id == Country.id)
            .where(Country.status == CountryStatus.active)
            .distinct()
        ).scalars().all()
    return set(rows)


def country_name_from_bundle(bundle_dir: Path) -> tuple[str | None, str | None]:
    """(iso2, name) from the bundle's admin0 COD-AB codes — factual, source-derived."""
    admin0 = bundle_dir / "data" / "admin0.geojson"
    if not admin0.exists():
        return None, None
    doc = json.loads(admin0.read_text(encoding="utf-8"))
    props = doc["features"][0]["properties"]
    return props.get("adm0_pcode"), props.get("adm0_name")


def generic_profile(iso3: str, iso2: str | None, name: str | None) -> CountryProfile:
    return CountryProfile(
        iso2=iso2,
        iso3=iso3,
        name=name,
        official_name=None,
        capital=None,
        region=None,
        languages=None,
        currency=None,
        timezone=None,
        levels=dict(GENERIC_LEVELS),
    )


def _ensure_bundle(iso3: str, url: str, tag: str) -> Path:
    """Download + extract the bundle; cached across runs."""
    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    marker = BUNDLE_ROOT / f".{iso3}-{tag}-done"
    if marker.exists():
        dirs = [d for d in BUNDLE_ROOT.glob(f"{iso3.lower()}-baseline-*") if d.is_dir()]
        if dirs:
            return dirs[0]
    zpath = BUNDLE_ROOT / f"{iso3.lower()}.zip"
    if not zpath.exists():
        print(f"  downloading {url} …")
        data = _fetch(url)
        zpath.write_bytes(data)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(BUNDLE_ROOT)
    dirs = [d for d in BUNDLE_ROOT.glob(f"{iso3.lower()}-baseline-*") if d.is_dir()]
    if not dirs:
        raise RuntimeError(f"bundle for {iso3} extracted no directory")
    marker.write_text("done")
    return dirs[0]


def run(only: list[str] | None = None, list_only: bool = False) -> None:
    assets = release_assets()
    done = onboarded_iso3s()
    plan = []
    for iso3, tag, url in assets:
        if iso3 in PROFILES and iso3 in done:
            continue  # hand-profiled and already onboarded (SWZ, KEN)
        if iso3 in done:
            continue
        plan.append((iso3, tag, url))
    if only:
        wanted = {c.upper() for c in only}
        plan = [p for p in plan if p[0] in wanted]
        done = done - wanted

    print(f"release countries: {len(assets)} | already onboarded: {len(done & {a[0] for a in assets})} "
          f"| planned: {len(plan)}")
    if list_only:
        for iso3, _tag, _url in plan:
            print(" ", iso3)
        return

    failures: list[tuple[str, str]] = []
    for i, (iso3, tag, url) in enumerate(plan, start=1):
        print(f"[{i}/{len(plan)}] {iso3}")
        try:
            bundle_dir = _ensure_bundle(iso3, url, tag)
            iso2, name = country_name_from_bundle(bundle_dir)
            profile = PROFILES.get(iso3) or generic_profile(iso3, iso2, name)
            _onboard_with_profile(bundle_dir, profile)
        except Exception as exc:  # keep the batch going; report at the end
            failures.append((iso3, f"{type(exc).__name__}: {exc}"))
            print(f"  FAILED {iso3}: {type(exc).__name__}: {exc}")

    print("\n=== batch summary ===")
    print(f"processed: {len(plan)} | failed: {len(failures)}")
    for iso3, err in failures:
        print(f"  {iso3}: {err}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None, help="comma-separated ISO3 subset")
    parser.add_argument("--list", action="store_true", help="show plan without onboarding")
    args = parser.parse_args()
    run(only=args.only.split(",") if args.only else None, list_only=args.list)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
