"""Vectorized chunked pixel-level Mann-Kendall, Sen's slope, and BH-FDR maps."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm

from terra_scientific.domain.models.dataset import ScientificGridStack
from terra_scientific.domain.models.request import SpatialConfig, TrendConfig
from terra_scientific.spatial.fdr import benjamini_hochberg_fdr
from terra_scientific.trends.sens_slope import elapsed_time_coordinate


@dataclass(frozen=True, slots=True)
class PixelTrendMaps:
    """2D gridded slope, p-value, BH q-value, and direction sign maps."""

    slopes: NDArray[np.float64]
    p_values: NDArray[np.float64]
    q_values: NDArray[np.float64]
    significant_fdr: NDArray[np.bool_]
    valid_pixel_mask: NDArray[np.bool_]
    fdr_significant_fraction: float
    positive_fraction: float
    negative_fraction: float


def compute_chunked_pixel_trends(
    stack: ScientificGridStack,
    *,
    trend_config: TrendConfig | None = None,
    spatial_config: SpatialConfig | None = None,
) -> PixelTrendMaps:
    """Compute pixel-by-pixel Sen's slope and MK test in row chunks to bound memory."""
    t_cfg = trend_config or TrendConfig()
    s_cfg = spatial_config or SpatialConfig()

    t_len, height, width = stack.data.shape
    slopes_out = np.full((height, width), np.nan, dtype=np.float64)
    pvals_out = np.full((height, width), np.nan, dtype=np.float64)
    aoi = stack.aoi_mask if stack.aoi_mask is not None else np.ones((height, width), dtype=bool)

    x_coord = elapsed_time_coordinate(stack.timestamps, time_unit=t_cfg.slope_time_unit)
    i_idx, j_idx = np.triu_indices(t_len, k=1)
    dt_pairs = x_coord[j_idx] - x_coord[i_idx]
    valid_dt = dt_pairs > 1e-12
    i_idx = i_idx[valid_dt]
    j_idx = j_idx[valid_dt]
    dt_pairs = dt_pairs[valid_dt][:, None]

    min_req = max(t_cfg.min_samples, int(np.ceil(t_len * s_cfg.min_pixel_coverage)), 4)

    for r0 in range(0, height, s_cfg.chunk_rows):
        r1 = min(r0 + s_cfg.chunk_rows, height)
        chunk = stack.data[:, r0:r1, :].reshape(t_len, -1)
        aoi_flat = aoi[r0:r1, :].ravel()
        valid_counts = np.sum(np.isfinite(chunk), axis=0)
        eligible = aoi_flat & (valid_counts >= min_req)
        if not np.any(eligible):
            continue

        el_chunk = chunk[:, eligible]
        dy_mat = el_chunk[j_idx, :] - el_chunk[i_idx, :]
        # Suppress divide/all-NaN warnings while evaluating finite pairwise differences.
        slopes_mat = dy_mat / dt_pairs
        with np.errstate(all="ignore"):
            med_slopes = np.nanmedian(slopes_mat, axis=0)

        s_vec = np.nansum(np.sign(dy_mat), axis=0)
        n_vec = valid_counts[eligible].astype(np.float64)
        var_vec = (n_vec * (n_vec - 1.0) * (2.0 * n_vec + 5.0)) / 18.0

        # Exact tie variance adjustment only for columns containing duplicate values.
        sorted_vals = np.sort(np.where(np.isfinite(el_chunk), el_chunk, np.inf), axis=0)
        diffs = np.diff(sorted_vals, axis=0)
        has_ties = np.any((diffs == 0.0) & np.isfinite(sorted_vals[:-1, :]), axis=0)
        if np.any(has_ties):
            for col in np.flatnonzero(has_ties):
                col_vals = el_chunk[:, col]
                finite_col = col_vals[np.isfinite(col_vals)]
                _, counts = np.unique(finite_col, return_counts=True)
                tie_corr = sum(float(t * (t - 1) * (2 * t + 5)) for t in counts if t > 1)
                n_c = float(finite_col.size)
                var_vec[col] = max((n_c * (n_c - 1.0) * (2.0 * n_c + 5.0) - tie_corr) / 18.0, 0.0)

        z_vec = np.zeros_like(s_vec)
        pos_mask = (s_vec > 0.0) & (var_vec > 0.0)
        neg_mask = (s_vec < 0.0) & (var_vec > 0.0)
        z_vec[pos_mask] = (s_vec[pos_mask] - 1.0) / np.sqrt(var_vec[pos_mask])
        z_vec[neg_mask] = (s_vec[neg_mask] + 1.0) / np.sqrt(var_vec[neg_mask])

        p_vec = np.ones_like(s_vec)
        var_pos = var_vec > 0.0
        p_vec[var_pos] = 2.0 * norm.sf(np.abs(z_vec[var_pos]))

        chunk_slopes = np.full(chunk.shape[1], np.nan, dtype=np.float64)
        chunk_p = np.full(chunk.shape[1], np.nan, dtype=np.float64)
        chunk_slopes[eligible] = med_slopes
        chunk_p[eligible] = p_vec

        slopes_out[r0:r1, :] = chunk_slopes.reshape(r1 - r0, width)
        pvals_out[r0:r1, :] = chunk_p.reshape(r1 - r0, width)

    valid_mask = np.isfinite(pvals_out)
    if t_cfg.apply_fdr_for_pixels:
        qvals, sig_mask = benjamini_hochberg_fdr(pvals_out, alpha=t_cfg.alpha)
    else:
        qvals = pvals_out.copy()
        sig_mask = valid_mask & (pvals_out <= t_cfg.alpha)

    valid_count = int(np.sum(valid_mask))
    if valid_count == 0:
        return PixelTrendMaps(
            slopes=slopes_out,
            p_values=pvals_out,
            q_values=qvals,
            significant_fdr=sig_mask,
            valid_pixel_mask=valid_mask,
            fdr_significant_fraction=0.0,
            positive_fraction=0.0,
            negative_fraction=0.0,
        )

    sig_frac = float(np.sum(sig_mask)) / valid_count
    pos_frac = float(np.sum(sig_mask & (slopes_out > 0.0))) / valid_count
    neg_frac = float(np.sum(sig_mask & (slopes_out < 0.0))) / valid_count

    return PixelTrendMaps(
        slopes=slopes_out,
        p_values=pvals_out,
        q_values=qvals,
        significant_fdr=sig_mask,
        valid_pixel_mask=valid_mask,
        fdr_significant_fraction=sig_frac,
        positive_fraction=pos_frac,
        negative_fraction=neg_frac,
    )
