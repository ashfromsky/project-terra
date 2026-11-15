"""Domain enumerations for Scientific Core."""

from enum import StrEnum


class PriorityTier(StrEnum):
    """Implementation and validation priority classification."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class AssessmentStatus(StrEnum):
    """Overall scientific assessment execution status."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_PARTIAL = "completed_partial"
    INSUFFICIENT_DATA = "insufficient_data"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class StageStatus(StrEnum):
    """Execution outcome for an individual analytical stage."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    INSUFFICIENT_DATA = "insufficient_data"
    FAILED = "failed"


class DataSourceId(StrEnum):
    """Supported Earth-observation and meteorological dataset identifiers."""

    MODIS_MOD13Q1 = "modis_mod13q1"
    MODIS_MOD11A2 = "modis_mod11a2"
    GPM_IMERG = "gpm_imerg"
    SMAP_SPL3SMP_E = "smap_spl3smp_e"
    NASA_POWER = "nasa_power"
    CUSTOM = "custom"
    NASA_GIBS = "nasa_gibs"


class VariableSemanticKind(StrEnum):
    """Physical aggregation semantics of a variable."""

    CONTINUOUS_INTENSIVE = "continuous_intensive"
    CONTINUOUS_EXTENSIVE = "continuous_extensive"
    CATEGORICAL = "categorical"
    QA_FLAG = "qa_flag"
    COORDINATE = "coordinate"


class TemporalSemantics(StrEnum):
    """How timestamps map onto physical time."""

    INSTANTANEOUS = "instantaneous"
    INTERVAL = "interval"
    COMPOSITE = "composite"
    CLIMATOLOGY = "climatology"


class TemporalCadence(StrEnum):
    """Nominal sampling or composite cadence."""

    HALF_HOURLY = "half_hourly"
    HOURLY = "hourly"
    DAILY = "daily"
    EIGHT_DAY = "eight_day"
    SIXTEEN_DAY = "sixteen_day"
    MONTHLY = "monthly"
    SEASONAL = "seasonal"
    ANNUAL = "annual"
    CUSTOM = "custom"


class QaPolicyLevel(StrEnum):
    """Quality-filtering strictness policy."""

    STRICT = "strict"
    STANDARD = "standard"
    PERMISSIVE = "permissive"


class AggregationOperator(StrEnum):
    """Supported temporal and spatial reduction operators."""

    MEAN = "mean"
    MEDIAN = "median"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    COUNT = "count"


class BaselineType(StrEnum):
    """Reference baseline construction strategy."""

    FIXED_REFERENCE = "fixed_reference"
    OUT_OF_SAMPLE = "out_of_sample"
    CROSS_VALIDATED = "cross_validated"
    FULL_PERIOD_EXPLICIT = "full_period_explicit"


class TrendDirection(StrEnum):
    """Mann-Kendall monotonic trend classification."""

    INCREASING = "increasing"
    DECREASING = "decreasing"
    NO_TREND = "no_trend"
    INSUFFICIENT_DATA = "insufficient_data"


class AutocorrelationPolicy(StrEnum):
    """How serial correlation is handled in trend inference."""

    DIAGNOSTIC_ONLY = "diagnostic_only"
    HAMED_RAO_MODIFIED_MK = "hamed_rao_modified_mk"
    PREWHITEN_YUE_WANG = "prewhiten_yue_wang"


class SeasonalGrouping(StrEnum):
    """Seasonal stratification scheme."""

    CALENDAR_MONTH = "calendar_month"
    COMPOSITE_DOY_BIN = "composite_doy_bin"
    QUARTERLY = "quarterly"
    EXPLICIT_GROUP = "explicit_group"


class ConfidenceTier(StrEnum):
    """Separated qualitative summary tier for quality or confidence dimensions."""

    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"


class OverpassMode(StrEnum):
    """SMAP AM/PM overpass stratification policy."""

    AM_ONLY = "am_only"
    PM_ONLY = "pm_only"
    AM_PM_SEPARATE = "am_pm_separate"
    AM_PM_MERGED_EXPLICIT = "am_pm_merged_explicit"
