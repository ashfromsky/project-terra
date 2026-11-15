"""QA policy and data-quality report models."""

from pydantic import BaseModel, ConfigDict, Field

from terra_scientific.domain.enums import DataSourceId, QaPolicyLevel


class QaPolicySpec(BaseModel):
    """Documented quality filtering rules derived from official product guides."""

    model_config = ConfigDict(frozen=True)

    policy_id: str
    level: QaPolicyLevel
    source_id: DataSourceId
    product: str
    product_version: str
    description: str
    accepted_flags: tuple[int, ...] = ()
    excluded_flags: tuple[int, ...] = ()
    bitmask_rules: dict[str, object] = Field(default_factory=dict)
    min_coverage_fraction: float = Field(default=0.7, ge=0.0, le=1.0)
    max_consecutive_missing: int | None = Field(default=None, ge=1)
    reference: str


class QualitySummary(BaseModel):
    """Quantitative quality-screening audit attached to every validated dataset."""

    model_config = ConfigDict(frozen=True)

    total_observations: int = Field(ge=0)
    valid_observations: int = Field(ge=0)
    filtered_by_qa: int = Field(default=0, ge=0)
    missing_or_fill: int = Field(default=0, ge=0)
    out_of_physical_range: int = Field(default=0, ge=0)
    valid_fraction: float = Field(ge=0.0, le=1.0)
    qa_distribution: dict[str, int] = Field(default_factory=dict)
    qa_policy_applied: str
    warnings: list[str] = Field(default_factory=list)
    passed_sufficiency: bool
