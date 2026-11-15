"""Global Moran's I and Local Getis-Ord Gi* spatial clustering with BH-FDR control."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm

from terra_scientific.spatial.fdr import benjamini_hochberg_fdr


@dataclass(frozen=True, slots=True)
class SpatialAutocorrelationSummary:
    """Global Moran's I and local Getis-Ord Gi* hotspot/coldspot output maps."""

    morans_i: float | None
    morans_z: float | None
    morans_p_value: float | None
    gi_star_z: NDArray[np.float64]
    hotspot_significant_fraction: float
    coldspot_significant_fraction: float


def _grid_neighbors(
    valid_mask: NDArray[np.bool_],
    *,
    connectivity: str = "queen",
) -> tuple[NDArray[np.int64], list[list[int]]]:
    """Build sparse Queen-8 or Rook-4 contiguity neighbor index lists for finite pixels."""
    coords = np.argwhere(valid_mask)
    index_grid = np.full(valid_mask.shape, -1, dtype=np.int64)
    for idx, (r, c) in enumerate(coords):
        index_grid[r, c] = idx

    height, width = valid_mask.shape
    rook_only = connectivity.strip().lower() == "rook"
    neighbors: list[list[int]] = []
    for r, c in coords:
        nbrs: list[int] = []
        r0, r1 = max(0, r - 1), min(height - 1, r + 1)
        c0, c1 = max(0, c - 1), min(width - 1, c + 1)
        for nr in range(r0, r1 + 1):
            for nc in range(c0, c1 + 1):
                if nr == r and nc == c:
                    continue
                if rook_only and nr != r and nc != c:
                    continue
                n_idx = int(index_grid[nr, nc])
                if n_idx >= 0:
                    nbrs.append(n_idx)
        neighbors.append(nbrs)
    return coords, neighbors


def compute_morans_i_and_hotspots(
    surface_2d: NDArray[np.float64],
    *,
    alpha: float = 0.05,
    permutations: int = 199,
    seed: int = 42,
    connectivity: str = "queen",
) -> SpatialAutocorrelationSummary:
    """Compute Global Moran's I and Local Getis-Ord Gi* using Queen or Rook weights."""
    valid_mask = np.isfinite(surface_2d)
    gi_map = np.full(surface_2d.shape, np.nan, dtype=np.float64)
    coords, neighbors = _grid_neighbors(valid_mask, connectivity=connectivity)
    n = len(coords)
    if n < 4:
        return SpatialAutocorrelationSummary(
            morans_i=None,
            morans_z=None,
            morans_p_value=None,
            gi_star_z=gi_map,
            hotspot_significant_fraction=0.0,
            coldspot_significant_fraction=0.0,
        )

    vals = np.array([surface_2d[r, c] for r, c in coords], dtype=np.float64)
    mean_x = float(np.mean(vals))
    dev = vals - mean_x
    denom = float(np.dot(dev, dev))
    if denom <= 1e-15:
        return SpatialAutocorrelationSummary(
            morans_i=None,
            morans_z=None,
            morans_p_value=None,
            gi_star_z=gi_map,
            hotspot_significant_fraction=0.0,
            coldspot_significant_fraction=0.0,
        )

    # Row-standardized Moran's I over linked cells.
    num = 0.0
    s0 = 0.0
    linked = 0
    for i, nbrs in enumerate(neighbors):
        if not nbrs:
            continue
        linked += 1
        w = 1.0 / float(len(nbrs))
        s0 += 1.0
        for j in nbrs:
            num += w * float(dev[i] * dev[j])

    if s0 <= 0.0 or linked < 4:
        return SpatialAutocorrelationSummary(
            morans_i=None,
            morans_z=None,
            morans_p_value=None,
            gi_star_z=gi_map,
            hotspot_significant_fraction=0.0,
            coldspot_significant_fraction=0.0,
        )

    morans_i = (float(n) / s0) * (num / denom)
    ei = -1.0 / float(n - 1)

    # Analytical randomization variance or permutation p-value.
    s1 = 0.0
    s2 = 0.0
    in_weights = np.zeros(n, dtype=np.float64)
    out_weights = np.zeros(n, dtype=np.float64)
    for i, nbrs in enumerate(neighbors):
        if not nbrs:
            continue
        wi = 1.0 / float(len(nbrs))
        out_weights[i] = 1.0
        for j in nbrs:
            in_weights[j] += wi
            wj = 1.0 / float(len(neighbors[j])) if neighbors[j] else 0.0
            s1 += 0.5 * ((wi + wj) ** 2)
    s2 = float(np.sum((out_weights + in_weights) ** 2))

    b2 = float(n * np.sum(dev**4)) / (denom**2)
    n_f = float(n)
    v_num = n_f * ((n_f**2 - 3.0 * n_f + 3.0) * s1 - n_f * s2 + 3.0 * (s0**2)) - b2 * (
        (n_f**2 - n_f) * s1 - 2.0 * n_f * s2 + 6.0 * (s0**2)
    )
    v_den = (n_f - 1.0) * (n_f - 2.0) * (n_f - 3.0) * (s0**2)
    var_i = max((v_num / v_den) - (ei**2), 1e-12) if v_den > 0.0 else 1e-12
    morans_z = (morans_i - ei) / float(np.sqrt(var_i))

    if permutations > 0:
        rng = np.random.default_rng(seed)
        extreme_count = 0
        abs_obs = abs(morans_i - ei)
        for _ in range(permutations):
            perm_dev = rng.permutation(dev)
            perm_num = 0.0
            for i, nbrs in enumerate(neighbors):
                if not nbrs:
                    continue
                wi = 1.0 / float(len(nbrs))
                perm_num += wi * float(perm_dev[i] * np.sum(perm_dev[nbrs]))
            perm_i = (n_f / s0) * (perm_num / denom)
            if abs(perm_i - ei) >= abs_obs:
                extreme_count += 1
        morans_p = float((extreme_count + 1) / (permutations + 1))
    else:
        morans_p = float(2.0 * norm.sf(abs(morans_z)))

    # Local Getis-Ord Gi* including focal cell i (w_{ii} = 1).
    s_std = float(np.sqrt(float(np.sum(dev**2)) / n_f))
    gi_pvals = np.full(n, np.nan, dtype=np.float64)
    if s_std > 1e-12:
        for i, nbrs in enumerate(neighbors):
            region_idx = [i, *nbrs]
            w_sum = float(len(region_idx))
            s1_i = w_sum
            denom_i = float(np.sqrt(max((n_f * s1_i - (w_sum**2)) / (n_f - 1.0), 1e-12))) * s_std
            gi_val = (float(np.sum(vals[region_idx])) - mean_x * w_sum) / denom_i
            r_c, c_c = coords[i]
            gi_map[r_c, c_c] = gi_val
            gi_pvals[i] = float(2.0 * norm.sf(abs(gi_val)))

    _, gi_sig = benjamini_hochberg_fdr(gi_pvals, alpha=alpha)
    gi_z_vec = np.array([gi_map[r, c] for r, c in coords], dtype=np.float64)
    hot_frac = float(np.sum(gi_sig & (gi_z_vec > 0.0))) / float(n)
    cold_frac = float(np.sum(gi_sig & (gi_z_vec < 0.0))) / float(n)

    return SpatialAutocorrelationSummary(
        morans_i=float(morans_i),
        morans_z=float(morans_z),
        morans_p_value=float(morans_p),
        gi_star_z=gi_map,
        hotspot_significant_fraction=hot_frac,
        coldspot_significant_fraction=cold_frac,
    )
