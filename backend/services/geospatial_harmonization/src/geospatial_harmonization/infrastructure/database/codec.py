"""Strict Pydantic-backed JSON serialization codecs for domain aggregates."""

from datetime import UTC, datetime
from typing import cast

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


def encode_dataset(dataset: SpatialDataset) -> dict[str, object]:
    """Serialize a SpatialDataset domain object into a JSON-compatible dict."""
    raw = _DATASET_ADAPTER.dump_python(dataset, mode="json", fallback=_json_fallback)
    return cast("dict[str, object]", raw)


def decode_dataset(payload: dict[str, object]) -> SpatialDataset:
    """Reconstruct and validate a SpatialDataset domain object from stored JSON."""
    return _DATASET_ADAPTER.validate_python(payload)


def encode_plan(plan: HarmonizationPlan) -> dict[str, object]:
    """Serialize a HarmonizationPlan domain object into a JSON-compatible dict."""
    raw = _PLAN_ADAPTER.dump_python(plan, mode="json", fallback=_json_fallback)
    return cast("dict[str, object]", raw)


def decode_plan(payload: dict[str, object]) -> HarmonizationPlan:
    """Reconstruct and validate a HarmonizationPlan domain object from stored JSON."""
    return _PLAN_ADAPTER.validate_python(payload)
