"""Canonical dataset and decoded intermediate representation domain models."""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    QualityPolicyViolationError,
)
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.temporal import TemporalSpec

DataFormat = Literal["hdf4", "hdf5", "netcdf", "geotiff", "zarr", "json", "csv", "unknown"]
SpatialRepresentation = Literal["raster", "point", "vector", "grid_series"]
VariableSemantics = Literal[
    "continuous_intensive", "continuous_extensive", "categorical", "qa_flag", "coordinate"
]


@dataclass(frozen=True, slots=True)
class AssetReference:
    """Immutable reference to a source, intermediate, or derived data asset."""

    asset_id: str
    uri: str
    data_format: DataFormat
    media_type: str
    checksum_sha256: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class VariableSpec:
    """Scientific metadata and scaling contract for a single dataset variable."""

    name: str
    units: str
    dtype: str
    dimensions: tuple[str, ...]
    semantics: VariableSemantics
    nodata: float | int | None = None
    scale_factor: float | None = None
    add_offset: float | None = None
    valid_range: tuple[float, float] | None = None
    grid: GridSpec | None = None
    attributes: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.units.strip():
            raise IncompatibleDatasetError("VariableSpec name and units must be non-empty")
        has_scaling = self.scale_factor is not None or self.add_offset is not None
        if self.semantics in ("categorical", "qa_flag") and has_scaling:
            raise QualityPolicyViolationError(
                f"'{self.name}' ({self.semantics}) must not carry scale_factor or add_offset"
            )
        if self.scale_factor is not None and (
            not math.isfinite(self.scale_factor) or self.scale_factor == 0.0
        ):
            raise IncompatibleDatasetError("scale_factor must be finite and non-zero")
        if self.valid_range is not None and self.valid_range[0] > self.valid_range[1]:
            raise IncompatibleDatasetError("valid_range minimum cannot exceed maximum")


@dataclass(frozen=True, slots=True)
class SpatialMetadata:
    """Spatial representation envelope supporting raster, point, and vector sources."""

    representation: SpatialRepresentation
    crs: str | None
    bounds: SpatialBounds | None = None
    grid: GridSpec | None = None
    point_count: int | None = None


@dataclass(frozen=True, slots=True)
class QualityMetadata:
    """Quality policy and exclusion summary without silent observation drops."""

    qa_policy: str
    valid_observation_fraction: float | None = None
    excluded_count: int = 0
    exclusion_reasons: tuple[str, ...] = ()
    flags_applied: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        frac = self.valid_observation_fraction
        if frac is not None and not 0.0 <= frac <= 1.0:
            raise QualityPolicyViolationError("valid_observation_fraction must be within [0, 1]")
        if self.excluded_count < 0:
            raise QualityPolicyViolationError("excluded_count cannot be negative")


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """Traceable origin and processing history for a dataset."""

    provider: str
    product: str
    product_version: str
    retrieved_at: datetime
    software_version: str
    run_type: str | None = None
    source_urls: tuple[str, ...] = ()
    processing_steps: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DecodedDataset:
    """Format-decoded intermediate representation independent of providers."""

    asset: AssetReference
    data_format: DataFormat
    variables: dict[str, VariableSpec]
    dimensions: dict[str, int]
    coordinates: dict[str, tuple[float | int | str, ...]] = field(default_factory=dict)
    arrays: dict[str, object] = field(default_factory=dict)
    attributes: dict[str, object] = field(default_factory=dict)
    crs: str | None = None
    grid: GridSpec | None = None
    temporal: TemporalSpec | None = None
    nodata: float | int | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.variables and not self.attributes:
            raise IncompatibleDatasetError("DecodedDataset must contain variables or attributes")
        if any(size < 0 for size in self.dimensions.values()):
            raise IncompatibleDatasetError("Dimension size cannot be negative")


@dataclass(frozen=True, slots=True)
class SpatialDataset:
    """Canonical handler output envelope preserving common fields and typed extensions."""

    dataset_id: UUID
    source_id: str
    provider: str
    product: str
    variables: dict[str, VariableSpec]
    units: dict[str, str]
    spatial_metadata: SpatialMetadata
    temporal_metadata: TemporalSpec
    quality_metadata: QualityMetadata
    assets: tuple[AssetReference, ...]
    provenance: ProvenanceRecord
    extensions: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(v.strip() for v in (self.source_id, self.provider, self.product)):
            raise IncompatibleDatasetError("source_id, provider, and product must be non-empty")
        if not self.variables:
            raise IncompatibleDatasetError("SpatialDataset must define at least one variable")
        for var_name, spec in self.variables.items():
            if self.units.get(var_name, spec.units) != spec.units:
                raise IncompatibleDatasetError(f"Unit mismatch for '{var_name}'")
