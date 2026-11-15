"""Versioned scientific method registry covering P0, P1, and explicitly deferred P2 methods."""

from pydantic import BaseModel, ConfigDict, Field

from terra_scientific.domain.enums import PriorityTier
from terra_scientific.domain.exceptions import MethodConfigurationError, MethodUnavailableError
from terra_scientific.domain.models.provenance import MethodReference


class MethodSpec(BaseModel):
    """Registered specification for one scientific algorithm or statistical test."""

    model_config = ConfigDict(frozen=True)

    method_id: str
    version: str
    name: str
    priority: PriorityTier
    implemented: bool
    formula_summary: str
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reference: str

    def to_reference(self, parameters: dict[str, object] | None = None) -> MethodReference:
        """Produce a runtime MethodReference for assessment provenance."""
        return MethodReference(
            method_id=self.method_id,
            version=self.version,
            name=self.name,
            priority=self.priority,
            implemented=self.implemented,
            parameters=parameters or {},
            formula_summary=self.formula_summary,
            assumptions=list(self.assumptions),
            limitations=list(self.limitations),
            reference=self.reference,
        )


class MethodRegistry:
    """Lookup registry ensuring every analytical calculation is versioned and cited."""

    def __init__(self, specs: dict[str, MethodSpec]) -> None:
        self._specs = dict(specs)

    def get(self, method_id: str) -> MethodSpec:
        """Return registered MethodSpec or raise MethodConfigurationError."""
        spec = self._specs.get(method_id)
        if spec is None:
            raise MethodConfigurationError(f"Unregistered scientific method: '{method_id}'")
        return spec

    def require_implemented(self, method_id: str) -> MethodSpec:
        """Return MethodSpec if implemented, else raise MethodUnavailableError."""
        spec = self.get(method_id)
        if not spec.implemented:
            raise MethodUnavailableError(
                f"Scientific method '{method_id}' ({spec.priority}) is deferred or unvalidated.",
                code="method_unavailable",
                details={"method_id": method_id, "priority": spec.priority.value},
            )
        return spec

    def list_all(self) -> list[MethodSpec]:
        """List all cataloged methods ordered by method_id."""
        return [self._specs[k] for k in sorted(self._specs)]

    def list_implemented(self) -> list[MethodSpec]:
        """List all implemented methods ordered by method_id."""
        return [spec for spec in self.list_all() if spec.implemented]


_SPECS: dict[str, MethodSpec] = {
    "qa_screening": MethodSpec(
        method_id="qa_screening",
        version="1.0.0",
        name="Source-Specific QA and Physical Range Screening",
        priority=PriorityTier.P0,
        implemented=True,
        formula_summary="Apply fill masking -> scale/offset -> physical bounds -> QA bitmask",
        assumptions=["Official NASA product scale factors, fill sentinels, and QA tables hold"],
        limitations=["Pixel-level QA metadata is absent if pre-aggregated external series lack QA"],
        reference="MOD13 User Guide v6.1; MOD11 User Guide v6.1; IMERG V07; SMAP SPL3SMP_E v6",
    ),
    "imerg_rate_to_depth": MethodSpec(
        method_id="imerg_rate_to_depth",
        version="1.0.0",
        name="IMERG Half-Hourly Precipitation Rate-to-Depth Integration",
        priority=PriorityTier.P0,
        implemented=True,
        formula_summary="depth_mm = sum(rate_mm_hr * dt_hr); dt_hr = 0.5 for 30-min intervals",
        assumptions=["Half-hourly rain rate is representative over its 30-minute interval"],
        limitations=["Missing half-hour steps remain NaN and never become zero precipitation"],
        reference="NASA GPM IMERG V07 Technical Documentation",
    ),
    "climatology_baseline": MethodSpec(
        method_id="climatology_baseline",
        version="1.0.0",
        name="Seasonal Reference Baseline Climatology",
        priority=PriorityTier.P0,
        implemented=True,
        formula_summary="Stratified bin mean, median, std, scaled MAD (1.4826*MAD), IQR, Q10/Q90",
        assumptions=["Reference period captures representative seasonal regimes without leakage"],
        limitations=["Requires multi-year coverage across each seasonal stratum"],
        reference="WMO Guidelines on the Calculation of Climate Normals (WMO-No. 1203)",
    ),
    "anomaly_detection": MethodSpec(
        method_id="anomaly_detection",
        version="1.0.0",
        name="Standardized, Robust Z-Score, and Percentile Anomaly Detection",
        priority=PriorityTier.P0,
        implemented=True,
        formula_summary="z = (x - mu)/sigma; z_robust = (x - median)/(1.4826*MAD); rank percentile",
        assumptions=["Reference dispersion sigma > 0 or MAD > 0 within each stratum"],
        limitations=["Near-zero variance strata yield undefined z-scores masked as null"],
        reference="Wilks (2019), Statistical Methods in the Atmospheric Sciences",
    ),
    "mann_kendall": MethodSpec(
        method_id="mann_kendall",
        version="1.0.0",
        name="Mann-Kendall Non-Parametric Monotonic Trend Test",
        priority=PriorityTier.P0,
        implemented=True,
        formula_summary=(
            "S = sum_{i<j} sgn(x_j - x_i); exact permutation p for n<=10, Z_c otherwise"
        ),
        assumptions=[
            "Independent observations unless an autocorrelation-adjusted variant is selected"
        ],
        limitations=["Tests monotonicity only; non-linear U-shaped trajectories yield low S"],
        reference="Mann (1945); Kendall (1975); Gilbert (1987)",
    ),
    "seasonal_mann_kendall": MethodSpec(
        method_id="seasonal_mann_kendall",
        version="1.0.0",
        name="Seasonal Mann-Kendall Test (Hirsch-Slack)",
        priority=PriorityTier.P0,
        implemented=True,
        formula_summary="S_total = sum_g S_g; Var(S_total) = sum_g Var(S_g)",
        assumptions=["Seasonal strata (calendar months or 16-day DOY bins) share monotonic sign"],
        limitations=["Assumes negligible inter-season serial dependence in standard formulation"],
        reference="Hirsch, Slack & Smith (1982), Water Resources Research",
    ),
    "sens_slope": MethodSpec(
        method_id="sens_slope",
        version="1.0.0",
        name="Theil-Sen Slope Estimator with Gilbert Confidence Interval",
        priority=PriorityTier.P0,
        implemented=True,
        formula_summary="Q = median((x_j - x_i)/(t_j - t_i)) over valid pairs t_j > t_i",
        assumptions=["Elapsed timestamps accurately represent sampling times"],
        limitations=["Confidence intervals assume independent residuals under unadjusted variance"],
        reference="Sen (1968), JASA; Gilbert (1987)",
    ),
    "autocorrelation_diagnostics": MethodSpec(
        method_id="autocorrelation_diagnostics",
        version="1.0.0",
        name="Serial Autocorrelation, Ljung-Box Q, Effective N, and Hamed-Rao / TFPW Options",
        priority=PriorityTier.P0,
        implemented=True,
        formula_summary="r_k ACF, Q = n(n+2)sum r_k^2/(n-k), ESS, Hamed-Rao variance inflation",
        assumptions=["Detrended residuals characterize serial persistence"],
        limitations=["Modified tests trade statistical power for reduced false positives"],
        reference="Hamed & Rao (1998); Yue & Wang (2002)",
    ),
    "spatial_zonal_stats": MethodSpec(
        method_id="spatial_zonal_stats",
        version="1.0.0",
        name="Area-Weighted Zonal Aggregation and Coverage Tracking",
        priority=PriorityTier.P0,
        implemented=True,
        formula_summary=(
            "Weighted mean using projected cell area or cos(lat) weights over valid mask"
        ),
        assumptions=["Grid mask matches AOI footprint within native/projected grid cell centers"],
        limitations=["Native coarse footprints (e.g. SMAP 36 km) cannot resolve sub-grid edges"],
        reference="PROJECT TERRA Spatial Harmonization Specification §6",
    ),
    "benjamini_hochberg_fdr": MethodSpec(
        method_id="benjamini_hochberg_fdr",
        version="1.1.0",
        name="Benjamini-Hochberg False Discovery Rate Control",
        priority=PriorityTier.P1,
        implemented=True,
        formula_summary="q_(i) = min_{k>=i}(min(1, m * p_(k) / k))",
        assumptions=["P-values across spatially neighboring pixels are valid under PRDS"],
        limitations=["Conservative under extreme negative dependence"],
        reference="Benjamini & Hochberg (1995), JRSS-B",
    ),
    "spatial_autocorrelation": MethodSpec(
        method_id="spatial_autocorrelation",
        version="1.0.0",
        name="Global Moran's I and Local Getis-Ord Gi* Hotspots",
        priority=PriorityTier.P1,
        implemented=True,
        formula_summary="Row-standardized spatial weight matrix (queen/kNN) Moran's I and Gi*",
        assumptions=["Stationarity of spatial process weights across valid cells"],
        limitations=["kNN/queen weights assume isotropic spatial contiguity"],
        reference="Moran (1950); Ord & Getis (1995)",
    ),
    "cross_variable_association": MethodSpec(
        method_id="cross_variable_association",
        version="1.0.0",
        name="Pearson, Spearman, Lagged Cross-Correlation, OLS, and Partial Correlation",
        priority=PriorityTier.P1,
        implemented=True,
        formula_summary="Pairwise/lagged r & rho, deseasonalized residuals, OLS & partial r",
        assumptions=["Compatible temporal/spatial support and non-collinear predictors"],
        limitations=[
            "Does not establish physical causality or rule out shared unobserved confounders"
        ],
        reference="Zar (2010); von Storch & Zwiers (1999)",
    ),
    "pettitt_change_point": MethodSpec(
        method_id="pettitt_change_point",
        version="1.0.0",
        name="Pettitt Non-Parametric Change-Point and Structural Break Detection",
        priority=PriorityTier.P1,
        implemented=True,
        formula_summary="K_T = max_t |U_{t,T}|, p approx 2*exp(-6*K_T^2/(T^3+T^2))",
        assumptions=["At most one dominant shift in location per segmented pass"],
        limitations=[
            "Identifies statistical shift only; physical cause requires external evidence"
        ],
        reference="Pettitt (1979), Applied Statistics",
    ),
    "event_recovery": MethodSpec(
        method_id="event_recovery",
        version="1.1.0",
        name="Event-Centered Post-Anomaly Recovery Quantification",
        priority=PriorityTier.P1,
        implemented=True,
        formula_summary=(
            "Pre-event finite baseline mean, trough magnitude, completeness ratio, and "
            "recovery bounded before next_event_idx after confirmation_steps consecutive finite "
            "observations >= target"
        ),
        assumptions=[
            "Seasonally adjusted series isolates departure from phenological cycle",
            (
                "Consecutive confirmation_steps prevent transient single-step crossings from "
                "declaring recovery"
            ),
        ],
        limitations=[
            "Truncated or subsequent-event-bounded post-event series marked incomplete_censored",
            (
                "Missing pre-event baseline values yield insufficient_data rather than "
                "fabricating baseline 0"
            ),
        ],
        reference="Ingrisch & Bahn (2018); De Keersmaecker et al. (2015)",
    ),
    "resilience_dimensions": MethodSpec(
        method_id="resilience_dimensions",
        version="1.1.0",
        name="Separated Ecosystem Resistance, Recovery, Stability, and Sensitivity Metrics",
        priority=PriorityTier.P1,
        implemented=True,
        formula_summary=(
            "Resistance=mean_i(1/(1+|z_neg_peak,i|)), Recovery=mean completeness, "
            "Stability=1/(1+std(standardized_deseasonalized_residuals)), Sensitivity=OLS slope "
            "(response_units/driver_units)"
        ),
        assumptions=[
            "Observable via remotely sensed proxies within native product caveats",
            (
                "Resistance requires >=1 eligible negative disturbance peak; absence of "
                "disturbance is unavailable"
            ),
        ],
        limitations=[
            "Measures statistical proxy behavior rather than species/trophic resilience",
            (
                "Cross-variable sensitivity coefficient is non-causal and conditioned on "
                "linear overlap"
            ),
        ],
        reference="Lloret et al. (2011); Hodgson et al. (2015)",
    ),
    "composite_tri": MethodSpec(
        method_id="composite_tri",
        version="0.0.0-unvalidated",
        name="Composite TERRA Resilience Index (TRI)",
        priority=PriorityTier.P2,
        implemented=False,
        formula_summary="Withheld composite aggregation",
        assumptions=["Domain-validated biome weighting and empirical calibration required"],
        limitations=["Withheld as unvalidated until calibration benchmarks exist (P2)"],
        reference="PROJECT TERRA Scientific Validation Charter §10",
    ),
    "critical_slowing_down": MethodSpec(
        method_id="critical_slowing_down",
        version="0.0.0-deferred",
        name="Critical Slowing Down / Early Warning Signals",
        priority=PriorityTier.P2,
        implemented=False,
        formula_summary=(
            "Rolling AR(1) and variance trend over stationary detrended high-freq series"
        ),
        assumptions=["Equidistant high-frequency continuous series without gap artifacts"],
        limitations=["Deferred to P2 research phase"],
        reference="Scheffer et al. (2009), Nature",
    ),
    "causal_attribution": MethodSpec(
        method_id="causal_attribution",
        version="0.0.0-deferred",
        name="Causal Attribution and Counterfactual Inference",
        priority=PriorityTier.P2,
        implemented=False,
        formula_summary="Deferred causal discovery / counterfactual framework",
        assumptions=["Explicit causal identification assumptions required"],
        limitations=["Deferred to P2 research phase; cross-variable correlation is non-causal"],
        reference="Pearl (2009); Runge et al. (2019)",
    ),
}

DEFAULT_METHOD_REGISTRY = MethodRegistry(_SPECS)
