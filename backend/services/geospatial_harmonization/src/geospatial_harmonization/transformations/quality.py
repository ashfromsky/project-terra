"""Quality policy validation and gate enforcement for harmonized and decoded datasets."""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from geospatial_harmonization.domain.exceptions import QualityPolicyViolationError
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    SpatialDataset,
    VariableSpec,
)
from geospatial_harmonization.domain.models.harmonization import QualityReport
from geospatial_harmonization.domain.models.temporal import require_tz_aware
from geospatial_harmonization.readers import ReaderRegistry, build_default_reader_registry
from geospatial_harmonization.transformations.transformer import default_local_asset_resolver


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    """Configurable scientific quality acceptance thresholds."""

    min_valid_fraction: float = 0.01
    fail_on_out_of_range: bool = True
    require_crs_for_raster: bool = True
    require_processing_provenance: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_valid_fraction <= 1.0:
            raise QualityPolicyViolationError("min_valid_fraction must lie within [0, 1]")


def _valid_mask(arr: NDArray[np.generic], spec: VariableSpec) -> NDArray[np.bool_]:
    if arr.dtype.kind == "f":
        mask = np.isfinite(arr)
        if spec.nodata is not None and not math.isnan(float(spec.nodata)):
            mask &= arr != float(spec.nodata)
        return mask
    mask = np.ones(arr.shape, dtype=np.bool_)
    if spec.nodata is not None and not math.isnan(float(spec.nodata)):
        mask &= arr != spec.nodata
    return mask


def _to_physical_values(
    arr: NDArray[np.generic], spec: VariableSpec, valid: NDArray[np.bool_], already_scaled: bool
) -> NDArray[np.float64]:
    vals = arr[valid].astype(np.float64, copy=False)
    if already_scaled or spec.semantics in ("qa_flag", "categorical"):
        return vals
    if spec.scale_factor is not None:
        vals = vals * spec.scale_factor
    if spec.add_offset is not None:
        vals = vals + spec.add_offset
    return vals


class QualityValidator:
    """Verifies spatial/temporal metadata, coverage fractions, and physical bounds."""

    def __init__(
        self,
        policy: QualityPolicy | None = None,
        reader_registry: ReaderRegistry | None = None,
        asset_resolver: Callable[[AssetReference], Path] | None = None,
    ) -> None:
        self._policy = policy or QualityPolicy()
        self._readers = reader_registry or build_default_reader_registry()
        self._asset_resolver = asset_resolver or default_local_asset_resolver

    def _check_metadata(
        self, dataset: SpatialDataset, errors: list[str], warnings: list[str]
    ) -> list[str]:
        checks = ["metadata_integrity"]
        require_tz_aware(dataset.provenance.retrieved_at, "provenance.retrieved_at")
        if self._policy.require_crs_for_raster and (
            dataset.spatial_metadata.representation in ("raster", "grid_series")
            and not dataset.spatial_metadata.crs
        ):
            errors.append("Raster dataset is missing explicit CRS in spatial_metadata")
        for name, spec in dataset.variables.items():
            if dataset.units.get(name, spec.units) != spec.units:
                errors.append(f"Unit mismatch for variable '{name}'")
        if self._policy.require_processing_provenance and not dataset.provenance.processing_steps:
            errors.append("Dataset provenance contains no recorded processing steps")
        if dataset.quality_metadata.excluded_count > 0:
            warnings.append(
                f"Dataset records {dataset.quality_metadata.excluded_count} excluded observations"
            )
        return checks

    def validate_arrays(
        self,
        dataset: SpatialDataset,
        arrays: Mapping[str, NDArray[np.generic]],
        *,
        already_scaled: bool = True,
    ) -> QualityReport:
        """Validate canonical dataset metadata together with per-variable raster/point arrays."""
        errors: list[str] = []
        warnings: list[str] = []
        checks = self._check_metadata(dataset, errors, warnings)

        total_valid = 0
        total_elements = 0
        checks.append("valid_observation_fraction")

        for var_name, spec in dataset.variables.items():
            if var_name not in arrays:
                errors.append(f"Variable '{var_name}' missing from validation arrays")
                continue
            arr = np.asarray(arrays[var_name])
            if arr.size == 0:
                errors.append(f"Variable '{var_name}' contains zero elements")
                continue
            valid = _valid_mask(arr, spec)
            v_count = int(np.count_nonzero(valid))
            total_valid += v_count
            total_elements += int(arr.size)

            if spec.valid_range is not None and v_count > 0:
                if "physical_valid_range" not in checks:
                    checks.append("physical_valid_range")
                lo, hi = spec.valid_range
                phys = _to_physical_values(arr, spec, valid, already_scaled)
                oob = int(np.count_nonzero((phys < lo) | (phys > hi)))
                if oob > 0:
                    msg = (
                        f"Variable '{var_name}' has {oob} pixel(s) outside valid_range [{lo}, {hi}]"
                    )
                    if self._policy.fail_on_out_of_range:
                        errors.append(msg)
                    else:
                        warnings.append(msg)

        valid_fraction = (
            min(1.0, max(0.0, total_valid / total_elements)) if total_elements > 0 else 0.0
        )
        nodata_fraction = min(1.0, max(0.0, 1.0 - valid_fraction))
        if valid_fraction < self._policy.min_valid_fraction or total_valid == 0:
            errors.append(
                f"Valid observation fraction {valid_fraction:.4f} is below policy "
                f"minimum {self._policy.min_valid_fraction:.4f}"
            )

        return QualityReport(
            passed=not errors,
            valid_fraction=valid_fraction,
            nodata_fraction=nodata_fraction,
            checks=tuple(checks),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    def validate_dataset_assets(
        self, dataset: SpatialDataset, *, already_scaled: bool = True
    ) -> QualityReport:
        """Decode dataset assets lazily via ReaderRegistry and run full quality validation."""
        arrays: dict[str, NDArray[np.generic]] = {}
        wanted = tuple(dataset.variables.keys())
        for asset in dataset.assets:
            if len(arrays) == len(wanted):
                break
            if asset.data_format in ("json", "csv") and len(dataset.assets) > 1:
                continue
            decoded = self._readers.read(asset, self._asset_resolver(asset), variables=None)
            for name in wanted:
                if name not in arrays and name in decoded.arrays:
                    arrays[name] = np.asarray(decoded.arrays[name])
        return self.validate_arrays(dataset, arrays, already_scaled=already_scaled)

    @staticmethod
    def enforce(report: QualityReport) -> QualityReport:
        """Raise QualityPolicyViolationError when a QualityReport failed acceptance checks."""
        if not report.passed:
            reason = "; ".join(report.errors) or "Quality policy check failed"
            raise QualityPolicyViolationError(reason)
        return report
