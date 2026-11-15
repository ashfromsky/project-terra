"""Trend analysis and serial correlation exports."""

from terra_scientific.trends.autocorrelation import (
    compute_sample_acf,
    diagnose_autocorrelation,
    hamed_rao_variance_factor,
    prewhiten_tfpw,
)
from terra_scientific.trends.mann_kendall import compute_mann_kendall
from terra_scientific.trends.seasonal_mk import compute_seasonal_mann_kendall
from terra_scientific.trends.sens_slope import (
    SensSlopeEstimate,
    compute_sens_slope,
    elapsed_time_coordinate,
    mk_tie_corrected_variance,
)

__all__ = [
    "SensSlopeEstimate",
    "compute_mann_kendall",
    "compute_sample_acf",
    "compute_seasonal_mann_kendall",
    "compute_sens_slope",
    "diagnose_autocorrelation",
    "elapsed_time_coordinate",
    "hamed_rao_variance_factor",
    "mk_tie_corrected_variance",
    "prewhiten_tfpw",
]
