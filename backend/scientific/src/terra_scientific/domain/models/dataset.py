"""Dataset, variable, spatial support, and array container contracts."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, model_validator

from terra_scientific.domain.enums import (
    DataSourceId,
    OverpassMode,
    VariableSemanticKind,
)
from terra_scientific.domain.exceptions import ScientificInputError
from terra_scientific.domain.models.temporal import TemporalMetadata, ensure_utc


class SpatialSupport(BaseModel):
    """CRS, native pixel spacing, effective footprint, and geometry bounds."""

    model_config = ConfigDict(frozen=True)

    crs: str
    nominal_resolution_m: float | None = Field(default=None, gt=0.0)
    native_footprint_m: float | None = Field(default=None, gt=0.0)
    bounds: tuple[float, float, float, float] | None = None
    grid_shape: tuple[int, int] | None = None
    pixel_area_m2: float | None = Field(default=None, gt=0.0)
    latitudes: list[float] | None = None
    longitudes: list[float] | None = None
    is_projected: bool = False
    transform: tuple[float, float, float, float, float, float] | None = None


class VariableMetadata(BaseModel):
    """Physical metadata, scale/offset status, fill values, and valid physical bounds."""

    model_config = ConfigDict(frozen=True)

    name: str
    canonical_name: str
    units: str
    semantic_kind: VariableSemanticKind
    scale_factor: float = 1.0
    add_offset: float = 0.0
    is_scaled: bool = True
    fill_values: tuple[float, ...] = ()
    valid_range: tuple[float, float] | None = None
    description: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)


class ObservationSeries(BaseModel):
    """Validated 1D temporal observation array with optional QA and overpass strata."""

    model_config = ConfigDict(frozen=True)

    timestamps: list[datetime]
    values: list[float | None]
    interval_starts: list[datetime] | None = None
    interval_ends: list[datetime] | None = None
    qa_layers: dict[str, list[int | None]] = Field(default_factory=dict)
    overpass_tags: list[str] | None = None
    metadata: VariableMetadata

    @model_validator(mode="after")
    def _validate_alignment(self) -> "ObservationSeries":
        normalized_ts = [ensure_utc(ts) for ts in self.timestamps]
        object.__setattr__(self, "timestamps", normalized_ts)

        n = len(normalized_ts)
        if len(self.values) != n:
            raise ValueError(
                f"Mismatched lengths for timestamps and values ({n} != {len(self.values)})"
            )
        if self.interval_starts is not None:
            if len(self.interval_starts) != n:
                raise ValueError("interval_starts length must match timestamps")
            object.__setattr__(
                self, "interval_starts", [ensure_utc(ts) for ts in self.interval_starts]
            )
        if self.interval_ends is not None:
            if len(self.interval_ends) != n:
                raise ValueError("interval_ends length must match timestamps")
            object.__setattr__(self, "interval_ends", [ensure_utc(ts) for ts in self.interval_ends])
        for qa_name, qa_vals in self.qa_layers.items():
            if len(qa_vals) != n:
                raise ValueError(
                    f"QA layer '{qa_name}' length ({len(qa_vals)}) must match timestamps ({n})"
                )
        if self.overpass_tags is not None and len(self.overpass_tags) != n:
            raise ValueError("overpass_tags length must match timestamps")
        for idx in range(1, n):
            if normalized_ts[idx] < normalized_ts[idx - 1]:
                raise ValueError("timestamps must be monotonically non-decreasing")
        return self

    def to_numpy(
        self,
    ) -> tuple[list[datetime], NDArray[np.float64], dict[str, NDArray[np.int64]]]:
        """Convert values to float64 with NaN for None and QA layers to int64 (-999999 sentinel)."""
        vals = np.array(
            [np.nan if v is None else float(v) for v in self.values],
            dtype=np.float64,
        )
        qa_np: dict[str, NDArray[np.int64]] = {}
        for qa_name, qa_list in self.qa_layers.items():
            qa_np[qa_name] = np.array(
                [-999999 if q is None else int(q) for q in qa_list],
                dtype=np.int64,
            )
        return list(self.timestamps), vals, qa_np


class ScientificDataset(BaseModel):
    """Canonical validated dataset accepted by Scientific Core stages."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    source_id: DataSourceId
    product: str
    product_version: str
    provider: str
    run_type: str | None = None
    overpass_mode: OverpassMode | None = None
    granule_ids: tuple[str, ...] = ()
    retrieval_timestamp: datetime | None = None
    spatial_support: SpatialSupport
    temporal_metadata: TemporalMetadata
    variables: dict[str, VariableMetadata]
    qa_layers: dict[str, str] = Field(default_factory=dict)
    series: dict[str, ObservationSeries] = Field(default_factory=dict)
    raster_refs: dict[str, str] = Field(default_factory=dict)
    ghs_dataset_id: str | None = None
    provenance_notes: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_scientific_contract(self) -> "ScientificDataset":
        provider_norm = self.provider.strip().lower()
        product_norm = self.product.strip().lower()
        if (
            self.source_id == DataSourceId.NASA_GIBS
            or "gibs" in provider_norm
            or "gibs" in product_norm
        ):
            raise ScientificInputError(
                "NASA GIBS is a contextual visualization tile source only and cannot be used "
                "for quantitative Scientific Core computations.",
                code="gibs_quantitative_prohibited",
                details={"provider": self.provider, "product": self.product},
            )
        if self.retrieval_timestamp is not None:
            object.__setattr__(self, "retrieval_timestamp", ensure_utc(self.retrieval_timestamp))
        return self


@dataclass(slots=True)
class ScientificGridStack:
    """In-memory 3D `[T, Y, X]` array container for vectorized pixel/spatial processing."""

    dataset_id: str
    source_id: DataSourceId
    product: str
    product_version: str
    variable: VariableMetadata
    spatial_support: SpatialSupport
    timestamps: list[datetime]
    data: NDArray[np.float64]
    qa_arrays: dict[str, NDArray[np.int64]] = field(default_factory=dict)
    cell_areas_m2: NDArray[np.float64] | None = None
    aoi_mask: NDArray[np.bool_] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.data.ndim != 3:
            raise ScientificInputError(
                f"ScientificGridStack.data must be 3D (T, Y, X), got shape {self.data.shape}"
            )
        if len(self.timestamps) != self.data.shape[0]:
            raise ScientificInputError(
                f"timestamps length ({len(self.timestamps)}) does not match data axis 0 "
                f"({self.data.shape[0]})"
            )
        self.timestamps = [ensure_utc(ts) for ts in self.timestamps]
        expected_spatial = self.data.shape[1:]
        if self.aoi_mask is not None and self.aoi_mask.shape != expected_spatial:
            raise ScientificInputError(
                f"aoi_mask shape {self.aoi_mask.shape} != grid shape {expected_spatial}"
            )
        if self.cell_areas_m2 is not None and self.cell_areas_m2.shape != expected_spatial:
            raise ScientificInputError(
                f"cell_areas_m2 shape {self.cell_areas_m2.shape} != grid shape {expected_spatial}"
            )
        for name, arr in self.qa_arrays.items():
            if arr.shape != self.data.shape:
                raise ScientificInputError(
                    f"QA array '{name}' shape {arr.shape} != data shape {self.data.shape}"
                )
