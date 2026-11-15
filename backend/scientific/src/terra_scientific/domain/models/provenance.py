"""Method provenance, reproducibility metadata, and artifact lineage models."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from terra_scientific.domain.enums import PriorityTier


class MethodReference(BaseModel):
    """Exact algorithmic metadata recorded whenever a scientific method executes."""

    model_config = ConfigDict(frozen=True)

    method_id: str
    version: str
    name: str
    priority: PriorityTier
    implemented: bool = True
    parameters: dict[str, object] = Field(default_factory=dict)
    formula_summary: str
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reference: str


class DatasetLineageEntry(BaseModel):
    """Source provenance recorded for one input dataset used in an assessment."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    source_id: str
    product: str
    product_version: str
    run_type: str | None = None
    granule_ids: tuple[str, ...] = ()
    crs: str
    nominal_resolution_m: float | None = None
    native_footprint_m: float | None = None
    retrieval_timestamp: datetime | None = None
    qa_policy_id: str | None = None
    ghs_dataset_id: str | None = None


class ProvenanceTrace(BaseModel):
    """Complete deterministic reproducibility manifest for a scientific assessment."""

    model_config = ConfigDict(frozen=True)

    trace_id: str
    package_name: str = "terra-scientific"
    package_version: str
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    dataset_lineage: list[DatasetLineageEntry] = Field(default_factory=list)
    harmonization_steps: list[str] = Field(default_factory=list)
    qa_policies_applied: list[str] = Field(default_factory=list)
    methods_invoked: list[MethodReference] = Field(default_factory=list)
    software_versions: dict[str, str] = Field(default_factory=dict)
    input_digest_sha256: str = ""
    deterministic_seed: int | None = None
