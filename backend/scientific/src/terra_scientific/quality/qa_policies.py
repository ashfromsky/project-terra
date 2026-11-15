"""Vectorized source-specific QA bitmask decoders grounded in official NASA user guides."""

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.enums import DataSourceId, QaPolicyLevel

QA_MISSING_SENTINEL = -999999


def evaluate_mod13_qa_mask(
    qa_arrays: dict[str, NDArray[np.int64]],
    level: QaPolicyLevel,
) -> tuple[NDArray[np.bool_], dict[str, int]]:
    """Build valid boolean mask from MOD13Q1 pixel_reliability and 16-bit VI Quality."""
    shape = next(iter(qa_arrays.values())).shape
    valid = np.ones(shape, dtype=bool)
    dist: dict[str, int] = {}

    pr = qa_arrays.get("pixel_reliability")
    if pr is not None:
        dist["pixel_reliability_good"] = int(np.sum(pr == 0))
        dist["pixel_reliability_marginal"] = int(np.sum(pr == 1))
        dist["pixel_reliability_snow_ice"] = int(np.sum(pr == 2))
        dist["pixel_reliability_cloudy"] = int(np.sum(pr == 3))
        dist["pixel_reliability_fill"] = int(np.sum(pr == -1))

        if level == QaPolicyLevel.STRICT:
            valid &= pr == 0
        else:
            valid &= np.isin(pr, [0, 1])

    vi_qual = qa_arrays.get("VI_Quality")
    if vi_qual is None:
        vi_qual = qa_arrays.get("vi_quality")
    if vi_qual is not None:
        valid_qa_bits = vi_qual != QA_MISSING_SENTINEL
        modland = vi_qual & 0b11
        usefulness = (vi_qual >> 2) & 0b1111
        adj_cloud = (vi_qual >> 8) & 0b1
        mixed_cloud = (vi_qual >> 10) & 0b1
        snow_ice = (vi_qual >> 14) & 0b1
        shadow = (vi_qual >> 15) & 0b1

        dist["vi_modland_good"] = int(np.sum(valid_qa_bits & (modland == 0)))
        dist["vi_modland_marginal"] = int(np.sum(valid_qa_bits & (modland == 1)))
        dist["vi_adjacent_cloud"] = int(np.sum(valid_qa_bits & (adj_cloud == 1)))
        dist["vi_snow_ice"] = int(np.sum(valid_qa_bits & (snow_ice == 1)))

        if level == QaPolicyLevel.STRICT:
            valid &= (
                valid_qa_bits
                & (modland == 0)
                & (usefulness <= 2)
                & (adj_cloud == 0)
                & (mixed_cloud == 0)
                & (snow_ice == 0)
                & (shadow == 0)
            )
        elif level == QaPolicyLevel.STANDARD:
            valid &= (
                valid_qa_bits
                & (modland <= 1)
                & (usefulness <= 6)
                & (adj_cloud == 0)
                & (mixed_cloud == 0)
                & (snow_ice == 0)
                & (shadow == 0)
            )
        else:
            valid &= valid_qa_bits & (modland <= 1) & (usefulness <= 10) & (mixed_cloud == 0)

    return valid, dist


def evaluate_mod11_qa_mask(
    qa_arrays: dict[str, NDArray[np.int64]],
    level: QaPolicyLevel,
) -> tuple[NDArray[np.bool_], dict[str, int]]:
    """Build valid boolean mask from MOD11A2 8-bit QC_Day or QC_Night flags."""
    shape = next(iter(qa_arrays.values())).shape
    valid = np.ones(shape, dtype=bool)
    dist: dict[str, int] = {}

    for key in ("QC_Day", "QC_Night", "qc_day", "qc_night", "qc"):
        qc = qa_arrays.get(key)
        if qc is None:
            continue
        present = qc != QA_MISSING_SENTINEL
        mandatory = qc & 0b11
        err_bits = (qc >> 6) & 0b11
        dist[f"{key}_mandatory_good"] = int(np.sum(present & (mandatory == 0)))
        dist[f"{key}_mandatory_other"] = int(np.sum(present & (mandatory == 1)))
        dist[f"{key}_cloud_or_unproduced"] = int(np.sum(present & (mandatory >= 2)))

        if level == QaPolicyLevel.STRICT:
            valid &= present & (mandatory == 0) & (err_bits == 0)
        elif level == QaPolicyLevel.STANDARD:
            valid &= present & (mandatory <= 1) & (err_bits <= 1)
        else:
            valid &= present & (mandatory <= 1) & (err_bits <= 2)

    return valid, dist


def evaluate_smap_qa_mask(
    qa_arrays: dict[str, NDArray[np.int64]],
    level: QaPolicyLevel,
) -> tuple[NDArray[np.bool_], dict[str, int]]:
    """Build valid boolean mask from SMAP retrieval_qual_flag and surface_flag."""
    shape = next(iter(qa_arrays.values())).shape
    valid = np.ones(shape, dtype=bool)
    dist: dict[str, int] = {}

    rqf = qa_arrays.get("retrieval_qual_flag")
    if rqf is not None:
        present = rqf != QA_MISSING_SENTINEL
        recommended_ok = (rqf & 0b1) == 0
        attempted_ok = ((rqf >> 2) & 0b1) == 0
        dist["smap_recommended_ok"] = int(np.sum(present & recommended_ok))
        dist["smap_not_recommended"] = int(np.sum(present & ~recommended_ok))
        if level in {QaPolicyLevel.STRICT, QaPolicyLevel.STANDARD}:
            valid &= present & recommended_ok & attempted_ok
        else:
            valid &= present & attempted_ok

    sflag = qa_arrays.get("surface_flag")
    if sflag is not None:
        present_s = sflag != QA_MISSING_SENTINEL
        dist["smap_clean_surface"] = int(np.sum(present_s & (sflag == 0)))
        dist["smap_surface_flagged"] = int(np.sum(present_s & (sflag != 0)))
        if level == QaPolicyLevel.STRICT:
            valid &= present_s & (sflag == 0)
        elif level == QaPolicyLevel.STANDARD:
            # Bits for water/frozen/snow/ice: reject non-zero surface condition flags.
            valid &= present_s & (sflag == 0)

    return valid, dist


def evaluate_source_qa(
    source_id: DataSourceId,
    qa_arrays: dict[str, NDArray[np.int64]],
    level: QaPolicyLevel,
) -> tuple[NDArray[np.bool_] | None, dict[str, int]]:
    """Dispatch source-appropriate vectorized QA bitmask evaluation."""
    if not qa_arrays:
        return None, {}
    if source_id == DataSourceId.MODIS_MOD13Q1:
        return evaluate_mod13_qa_mask(qa_arrays, level)
    if source_id == DataSourceId.MODIS_MOD11A2:
        return evaluate_mod11_qa_mask(qa_arrays, level)
    if source_id == DataSourceId.SMAP_SPL3SMP_E:
        return evaluate_smap_qa_mask(qa_arrays, level)
    return None, {}
