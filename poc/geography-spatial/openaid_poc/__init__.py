"""OpenAid geography & spatial proof of concept.

Validates the two highest-risk foundations of the OpenAid blueprint (§16):

1. Country-configurable administrative hierarchies (variable depth, local
   level names, no country-specific application code).
2. Spatial data ingestion, storage, validation and querying in
   PostgreSQL/PostGIS.

**This PoC uses SYNTHETIC fixtures that are not real-world data.** See
``fixtures/README.md``.
"""

__version__ = "0.1.0"
