# OpenAid — Product Requirements

> Source of truth: `OpenAid_Project_Blueprint.docx` (November 2026). This
> document restates the product requirements in engineering-consumable form
> and records the decisions taken. Where this file and the blueprint
> disagree, the blueprint wins until the divergence is explicitly resolved.

## 1. Mission & positioning

- **Mission:** Make reliable humanitarian, geographical, demographic and
  community-development information accessible and actionable across Africa.
- **Positioning:** An open intelligence platform for Africa's communities and
  the humanitarian ecosystem — not a dashboard, not a directory.
- **Tagline:** "Open data. Stronger communities. Better decisions."

## 2. Confirmed product decisions

| Decision | Value |
| --- | --- |
| Geographic scope | Africa-wide from day one (architecture), progressive data onboarding |
| Access model | Public exploration by default; controlled contribution & review |
| Product identity | Balanced hybrid of humanitarian intelligence and community development |
| Deployment | Centralised, cloud-hosted platform |
| Differentiator | Balanced combination of geospatial mapping, open data infrastructure and AI |
| Name | OpenAid |
| Licence (code) | GNU AGPL-3.0 (subject to governance review) |
| Tooling | Free and open source only |

## 3. Users & jobs to be done

| User | Jobs |
| --- | --- |
| Public visitors & community members | Explore country and local profiles; find public services; understand what evidence exists and where it is missing |
| Humanitarian organisations | Inspect documented operational presence, service distribution and potential geographic gaps |
| Researchers & analysts | Discover datasets; reproduce calculations; compare geographies; inspect provenance and limitations |
| Government & development practitioners | Inspect baseline indicators and service-access evidence |
| Data contributors | Submit corrections, datasets and organisation/facility updates for review; track review status |
| Developers | Integrate with documented, versioned public APIs |

## 4. Product modules

| # | Module | Summary | Phase |
| --- | --- | --- | --- |
| 4.1 | Geographic intelligence | Africa-wide interactive map, boundaries, layer controls, search, choropleths, vector tiles | 1 |
| 4.2 | Country profiles & configuration | ISO identity, dynamic administrative levels, source registry, data-readiness | 1 |
| 4.3 | Organisation registry | NGOs/UN/government/CBO directory with explicit presence model (HQ ≠ office ≠ operations) | 1 |
| 4.4 | Services & facilities directory | Facilities, service offerings, managing organisations, operational status, validity dates | 1 |
| 4.5 | Baseline intelligence & indicators | Demographic/health/education/WASH/economy/climate observations tied to geography, period, source, methodology | 1–3 |
| 4.6 | Open data catalogue | Datasets with publisher, licence, coverage, versions, lineage, access class separate from reuse licence | 1 |
| 4.7 | Data ingestion & QC | CSV/XLSX/JSON/GeoJSON/Shapefile/GeoPackage ingestion, validation, review, controlled publishing | 2 |
| 4.8 | Needs & coverage analysis | Population-to-facility ratios, proximity analysis — never conflated with service quality | 3 |
| 4.9 | AI intelligence assistant | Source-grounded retrieval and analysis over approved tools only; never unrestricted SQL | 4 |
| 4.10 | Reporting & exports | Country/district profiles, maps, PDF/CSV/XLSX/GeoJSON/GeoPackage exports with caveats | 3 |
| 4.11 | Governance & contributions | Auth, roles, submissions, reviews, audit logs | 2 |
| 4.12 | Developer ecosystem | Documented, versioned REST API with rate limits | 4 |

## 5. Access model

Public-by-default means **public exploration where data rights and safety
permit**. Access classification (Public / Restricted / Confidential /
Sensitive) is stored separately from the reuse licence. Never published:
beneficiary-level personal data, medical records, sensitive protection data,
protected locations.

| Role | Capabilities |
| --- | --- |
| Anonymous visitor | Explore public maps, profiles, datasets, indicators, organisations, facilities; rate-limited public API |
| Registered contributor | Save collections; submit corrections/datasets/updates for review |
| Reviewer | Approve/reject/request changes within assigned scope |
| Administrator | Platform settings, country configuration, permissions, governance |
| Organisation representative | Manage own organisation profile after identity/authority checks |

## 6. Definition of success

1. A visitor can explore countries, discover documented organisations, find
   essential services, inspect baseline indicators, download datasets and see
   where information is missing.
2. A researcher can reproduce analytical results and inspect source and
   methodology.
3. A humanitarian organisation can understand documented geographic presence
   and potential service gaps without confusing proximity with service
   quality.
4. A developer can build on documented public APIs.
5. A contributor can submit information and track whether it has been
   reviewed.
6. The platform clearly communicates data coverage, quality, freshness,
   uncertainty and licensing.

## 7. Out of scope (permanently or for now)

- Beneficiary-level personal data collection (permanently).
- Microservices / Kubernetes in early phases (modular monolith first).
- Any proprietary or paid-only toolchain (project constraint: free & open
  source only).
- Claims of continental completeness — coverage gaps are shown explicitly.
