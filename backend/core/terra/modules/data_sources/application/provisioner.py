"""Adaptive horizon expansion and multi-provider candidate resolution for Core ingestion."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from terra_scientific.domain.enums import (
    BaselineType,
    DataSourceId,
    QaPolicyLevel,
    TemporalCadence,
)
from terra_scientific.domain.models.request import AssessmentRequest, BaselineConfig, TrendConfig

BBoxTuple = tuple[float, float, float, float]

_ARCHIVE_START_BY_PROVIDER: dict[str, datetime] = {
    "nasa_power": datetime(1981, 1, 1, tzinfo=UTC),
    "modis": datetime(2000, 2, 18, tzinfo=UTC),
    "gpm_imerg": datetime(2000, 6, 1, tzinfo=UTC),
    "smap": datetime(2015, 3, 31, tzinfo=UTC),
}

_PROVIDER_DOMAIN_TAGS: dict[str, set[str]] = {
    "nasa_power": {"climate", "precipitation"},
    "modis": {"vegetation", "lst"},
    "gpm_imerg": {"precipitation"},
    "smap": {"soil_moisture"},
}


@dataclass(frozen=True, slots=True)
class ProviderCandidate:
    """Single compatible provider/product ingestion option for an ecological domain."""

    domain: str
    provider: str
    product: str
    variables: list[str]
    parameters: list[str]
    run_type: str | None = None
    overpass: str | None = None


def ensure_utc(dt: datetime) -> datetime:
    """Normalize naive or offset datetimes to UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def parse_iso_datetime(raw: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp string into UTC datetime if valid."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    normalized = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return ensure_utc(parsed)


def compute_adaptive_provision_window(
    analysis_start: datetime,
    analysis_end: datetime,
    *,
    baseline_type: str,
    reference_start: datetime | None,
    reference_end: datetime | None,
    min_reference_years: int,
) -> tuple[datetime, datetime, bool, str | None]:
    """Compute required ingestion [start, end] satisfying baseline history and trend span."""
    start_utc = ensure_utc(analysis_start)
    end_utc = ensure_utc(analysis_end)
    years_needed = max(1, min_reference_years)
    prov_start = start_utc
    prov_end = end_utc
    reasons: list[str] = []

    if reference_start is not None:
        ref_s = ensure_utc(reference_start)
        if ref_s < prov_start:
            prov_start = ref_s
            reasons.append("Extended start to cover explicit historical reference baseline.")
    elif baseline_type in {"out_of_sample", "fixed_reference"}:
        target_start = start_utc - timedelta(days=366 * years_needed + 15)
        if target_start < prov_start:
            prov_start = target_start
            reasons.append(
                f"Expanded start by {years_needed} yr before analysis_start to populate "
                f"{baseline_type} baseline without data leakage."
            )
    else:
        min_span = timedelta(days=366 * max(2, years_needed))
        if (end_utc - start_utc) < min_span:
            prov_start = end_utc - min_span
            reasons.append(
                f"Expanded start to ensure >= {max(2, years_needed)} yr of seasonal coverage."
            )

    if reference_end is not None:
        ref_e = ensure_utc(reference_end)
        if ref_e > prov_end:
            prov_end = ref_e

    min_archive = _ARCHIVE_START_BY_PROVIDER["nasa_power"]
    if prov_start < min_archive:
        prov_start = min_archive

    expanded = prov_start < start_utc or prov_end > end_utc
    return prov_start, prov_end, expanded, "; ".join(reasons) if reasons else None


def domain_candidates(
    domain: str,
    *,
    span_days: float,
) -> list[ProviderCandidate]:
    """Return ordered compatible provider/product candidates with real fallbacks."""
    norm = domain.strip().lower()
    if norm == "climate":
        return [
            ProviderCandidate(
                domain="climate",
                provider="nasa_power",
                product="power_daily",
                variables=[],
                parameters=[
                    "T2M",
                    "T2M_MAX",
                    "T2M_MIN",
                    "PRECTOTCORR",
                    "RH2M",
                    "ALLSKY_SFC_SW_DWN",
                ],
            )
        ]
    if norm == "vegetation":
        return [
            ProviderCandidate(
                domain="vegetation",
                provider="modis",
                product="MOD13Q1.061",
                variables=["NDVI", "EVI", "pixel_reliability", "VI_Quality"],
                parameters=[],
            ),
            ProviderCandidate(
                domain="vegetation",
                provider="modis",
                product="MOD11A2.061",
                variables=["LST_Day_1km", "QC_Day"],
                parameters=[],
            ),
        ]
    if norm == "precipitation":
        imerg = [
            ProviderCandidate(
                domain="precipitation",
                provider="gpm_imerg",
                product="GPM_3IMERGHH.07",
                variables=["precipitation", "precipitationQualityIndex"],
                parameters=[],
                run_type="Final",
            ),
            ProviderCandidate(
                domain="precipitation",
                provider="gpm_imerg",
                product="GPM_3IMERGHHL.07",
                variables=["precipitation", "precipitationQualityIndex"],
                parameters=[],
                run_type="Late",
            ),
        ]
        power_precip = ProviderCandidate(
            domain="precipitation",
            provider="nasa_power",
            product="power_daily",
            variables=[],
            parameters=["PRECTOTCORR"],
        )
        return [power_precip, *imerg] if span_days > 30.0 else [*imerg, power_precip]
    if norm == "soil_moisture":
        return [
            ProviderCandidate(
                domain="soil_moisture",
                provider="smap",
                product="SPL3SMP_E.006",
                variables=["soil_moisture", "retrieval_qual_flag", "surface_flag"],
                parameters=[],
                overpass="AM",
            )
        ]
    return []


def estimate_max_granules(
    provider: str,
    product: str,
    start: datetime,
    end: datetime,
    cap: int,
) -> int:
    """Compute bounded granule count required to sample full multi-year horizon."""
    days = max(1, (end - start).days + 1)
    if provider == "modis":
        step_days = 8 if "11A2" in product else 16
        needed = days // step_days + 4
    elif provider == "smap":
        needed = min(days + 2, 180)
    elif provider == "gpm_imerg":
        needed = min(days * 2, 180)
    else:
        needed = 24
    return max(12, min(cap, 256, needed))


def clamp_window_to_provider_archive(
    provider: str,
    start: datetime,
    end: datetime,
) -> tuple[datetime, datetime] | None:
    """Restrict provisioning window to provider archive start; return None if unsupported."""
    archive_start = _ARCHIVE_START_BY_PROVIDER.get(provider)
    clamped_start = max(start, archive_start) if archive_start else start
    if end <= clamped_start:
        return None
    return clamped_start, end


def _bboxes_overlap(a: BBoxTuple, b: BBoxTuple) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def dataset_matches_provision_target(
    summary: dict[str, Any],
    *,
    domain: str,
    bbox: BBoxTuple,
    prov_start: datetime,
    prov_end: datetime,
    target_cadence: str,
) -> bool:
    """Return True if an already-prepared GHS dataset satisfies domain, AOI, and horizon."""
    provider = str(summary.get("provider", "")).lower()
    if domain not in _PROVIDER_DOMAIN_TAGS.get(provider, set()):
        return False
    obs_count = int(summary.get("observation_count") or 0)
    if obs_count < 6:
        return False

    ds_cadence = str(summary.get("temporal_cadence") or "").strip().lower()
    if (
        target_cadence
        and ds_cadence
        and ds_cadence not in {target_cadence.lower(), "daily", "custom"}
        and target_cadence.lower() == "monthly"
        and ds_cadence in {"annual", "quarterly"}
    ):
        return False

    ds_start = parse_iso_datetime(summary.get("temporal_start"))
    ds_end = parse_iso_datetime(summary.get("temporal_end"))
    if ds_start is None or ds_end is None:
        return False
    tolerance = timedelta(days=45)
    if ds_start > prov_start + tolerance or ds_end < prov_end - tolerance:
        return False

    spatial = summary.get("spatial_metadata") or {}
    bounds = spatial.get("bounds") if isinstance(spatial, dict) else None
    ds_bbox: BBoxTuple | None = None
    try:
        if isinstance(bounds, dict) and {"min_x", "min_y", "max_x", "max_y"}.issubset(
            bounds.keys()
        ):
            ds_bbox = (
                float(bounds["min_x"]),
                float(bounds["min_y"]),
                float(bounds["max_x"]),
                float(bounds["max_y"]),
            )
        elif isinstance(bounds, list | tuple) and len(bounds) == 4:
            ds_bbox = (
                float(bounds[0]),
                float(bounds[1]),
                float(bounds[2]),
                float(bounds[3]),
            )
    except (TypeError, ValueError):
        return False

    if ds_bbox is None:
        return False
    if not (
        -180.0 <= ds_bbox[0] <= ds_bbox[2] <= 180.0 and -90.0 <= ds_bbox[1] <= ds_bbox[3] <= 90.0
    ):
        return False
    return _bboxes_overlap(ds_bbox, bbox)


def build_readiness_request(
    *,
    analysis_start: datetime,
    analysis_end: datetime,
    target_cadence: str,
    baseline_type: str,
    reference_start: datetime | None,
    reference_end: datetime | None,
    min_reference_years: int,
    qa_level: str,
    source_ids: list[DataSourceId] | None = None,
) -> AssessmentRequest:
    """Build AssessmentRequest matching Core UI / auto-provisioning options."""
    try:
        cadence_enum = TemporalCadence(target_cadence)
    except ValueError:
        cadence_enum = TemporalCadence.MONTHLY
    try:
        baseline_enum = BaselineType(baseline_type)
    except ValueError:
        baseline_enum = BaselineType.OUT_OF_SAMPLE
    try:
        qa_enum = QaPolicyLevel(qa_level)
    except ValueError:
        qa_enum = QaPolicyLevel.STRICT

    return AssessmentRequest(
        request_id="provision-readiness-check",
        analysis_start=ensure_utc(analysis_start),
        analysis_end=ensure_utc(analysis_end),
        source_ids=list(source_ids or []),
        target_cadence=cadence_enum,
        qa_level=qa_enum,
        baseline=BaselineConfig(
            baseline_type=baseline_enum,
            reference_start=ensure_utc(reference_start) if reference_start else None,
            reference_end=ensure_utc(reference_end) if reference_end else None,
            min_reference_years=max(1, min_reference_years),
            min_samples_per_period=min(3, max(1, min_reference_years)),
        ),
        trend=TrendConfig(use_seasonal_mk=True),
    )
