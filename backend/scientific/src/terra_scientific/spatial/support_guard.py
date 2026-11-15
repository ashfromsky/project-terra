"""Spatial support checks comparing native pixel spacing and physical sensor footprint."""

from terra_scientific.domain.models.dataset import SpatialSupport


def check_spatial_support_compatibility(
    left_name: str,
    left_support: SpatialSupport,
    right_name: str,
    right_support: SpatialSupport,
    *,
    disparity_ratio_threshold: float = 5.0,
) -> list[str]:
    """Emit explicit scientific caveats when footprints or CRS projections differ strongly."""
    warnings: list[str] = []
    if left_support.crs != right_support.crs:
        warnings.append(
            f"Spatial CRS differs between '{left_name}' and '{right_name}'; ensure harmonized "
            "reprojection prior to pixel-level overlays."
        )

    eff_left = left_support.native_footprint_m or left_support.nominal_resolution_m
    eff_right = right_support.native_footprint_m or right_support.nominal_resolution_m
    if eff_left is not None and eff_right is not None and min(eff_left, eff_right) > 0.0:
        ratio = max(eff_left, eff_right) / min(eff_left, eff_right)
        if ratio >= disparity_ratio_threshold:
            warnings.append(
                f"Large spatial footprint disparity (~{ratio:.1f}x) between '{left_name}' "
                f"(~{eff_left:.0f} m) and '{right_name}' (~{eff_right:.0f} m); coarse data "
                "does not resolve fine sub-grid heterogeneity."
            )
    return warnings
