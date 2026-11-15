"""Strict Pydantic-backed JSON serialization codecs for domain aggregates."""

import math
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import TypeAdapter

from geospatial_harmonization.domain.models.dataset import SpatialDataset
from geospatial_harmonization.domain.models.harmonization import HarmonizationPlan

_DATASET_ADAPTER: TypeAdapter[SpatialDataset] = TypeAdapter(SpatialDataset)
_PLAN_ADAPTER: TypeAdapter[HarmonizationPlan] = TypeAdapter(HarmonizationPlan)


def ensure_utc(value: datetime) -> datetime:
    """Normalize naive (SQLite) or offset timestamps to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_fallback(obj: object) -> object:
    item_fn = getattr(obj, "item", None)
    if callable(item_fn):
        return item_fn()
    return str(obj)


_NAN_SENTINEL = "__terra_non_finite_nan__"
_INF_SENTINEL = "__terra_non_finite_inf__"
_NEG_INF_SENTINEL = "__terra_non_finite_neg_inf__"


def _finite_json(value: Any) -> Any:
    """Replace non-finite floats with JSON-safe sentinels for PostgreSQL JSON."""
    if isinstance(value, float):
        if math.isnan(value):
            return _NAN_SENTINEL
        if math.isinf(value):
            return _INF_SENTINEL if value > 0 else _NEG_INF_SENTINEL
        return value
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_finite_json(item) for item in value]
    return value


def _restore_non_finite(value: Any) -> Any:
    """Restore non-finite float sentinels produced by :func:`_finite_json`."""
    if value == _NAN_SENTINEL:
        return float("nan")
    if value == _INF_SENTINEL:
        return float("inf")
    if value == _NEG_INF_SENTINEL:
        return float("-inf")
    if isinstance(value, dict):
        return {key: _restore_non_finite(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_restore_non_finite(item) for item in value]
    return value


def encode_dataset(dataset: SpatialDataset) -> dict[str, object]:
    """Serialize a SpatialDataset domain object into a JSON-compatible dict."""
    raw = _DATASET_ADAPTER.dump_python(dataset, mode="json", fallback=_json_fallback)
    return cast("dict[str, object]", _finite_json(raw))


def decode_dataset(payload: dict[str, object]) -> SpatialDataset:
    """Reconstruct and validate a SpatialDataset domain object from stored JSON."""
    return _DATASET_ADAPTER.validate_python(_restore_non_finite(payload))


def encode_plan(plan: HarmonizationPlan) -> dict[str, object]:
    """Serialize a HarmonizationPlan domain object into a JSON-compatible dict."""
    raw = _PLAN_ADAPTER.dump_python(plan, mode="json", fallback=_json_fallback)
    return cast("dict[str, object]", _finite_json(raw))


def decode_plan(payload: dict[str, object]) -> HarmonizationPlan:
    """Reconstruct and validate a HarmonizationPlan domain object from stored JSON."""
    return _PLAN_ADAPTER.validate_python(_restore_non_finite(payload))
