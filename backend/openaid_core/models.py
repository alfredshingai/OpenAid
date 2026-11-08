"""Aggregated model imports so Alembic (and tests) see the full metadata."""

from .datasets.models import (  # noqa: F401
    AccessClass,
    Dataset,
    DatasetFile,
    DatasetVersion,
    DataSource,
)
from .facilities.models import (  # noqa: F401
    Facility,
    FacilityOrgRole,
    FacilityOrganisation,
    FacilityService,
    FacilityType,
    OperationalStatus,
)
from .geography.models import (  # noqa: F401
    AdministrativeLevel,
    AdministrativeUnit,
    BoundaryVersion,
    Country,
    CountryConfiguration,
    CountryStatus,
    ImportBatch,
    ImportFormat,
    ImportStatus,
    QuarantinedFeature,
    VerificationStatus,
)
from .indicators.models import (  # noqa: F401
    AggregationMethod,
    ComparabilityAssessment,
    ComparabilityAssessmentRecord,
    IndicatorCategory,
    IndicatorDefinition,
    IndicatorObservation,
    MeasurementType,
    MissingType,
    ValueType,
)
from .models_base import Base  # noqa: F401
from .organisations.models import (  # noqa: F401
    OfficeType,
    Organisation,
    OrganisationLocation,
    OrganisationSector,
    OrganisationType,
)
