# Fixtures — ⚠️ 100% SYNTHETIC TEST DATA ⚠️

Everything in this directory is **artificial sample data created for
development and testing**. The countries, boundaries, codes and names are
invented. They must **never** be presented as real-world evidence.

Country codes are taken from the ISO 3166 **user-assigned range**
(XA–XZ / XAA–XZZ) so they can never collide with real countries.

| Directory | Country | Levels | Shape |
| --- | --- | --- | --- |
| `XA_alandra/` | Alandra (synthetic) | 2 — Region → District | 3 regions, 6 districts |
| `XB_boroland/` | Boroland (synthetic) | 3 — Province → County → Ward | 2 provinces, 4 counties, 8 wards |
| `XC_cyria/` | Cyria (synthetic) | 4 — Governorate → Department → Commune → Village | 1 governorate, 2 departments, 4 communes, 8 villages |

Each directory contains:

- `country.yaml` — country identity + administrative level configuration
  (the data that drives dynamic hierarchy behaviour).
- `boundary.geojson` — synthetic boundaries in EPSG:4326 with the property
  contract: `country_iso3`, `official_code`, `source_unit_id`, `name`,
  `admin_level`, `parent_code`.

Regenerate deterministically with:

```bash
python scripts/make_fixtures.py
```

For a **real-data** demonstration (with provenance), see
`scripts/ingest_real_demo.py` — it ingests one country's boundaries from the
open-source `crisis-baseline-kit` project release (OCHA COD-AB via HDX,
CC BY IGO), clearly labelled as real data with its licence recorded.
