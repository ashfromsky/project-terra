"""Color ramp palettes aligned with frontend entities/layer/model/color-ramps.ts."""

from terra.modules.layers.domain.entities import ColorRampStop

VEGETATION_RAMP: tuple[ColorRampStop, ...] = (
    ColorRampStop(0.0, "#dfb892", (223, 184, 146), "Bare / Sparse"),
    ColorRampStop(0.25, "#d9e3a3", (217, 227, 163), "Low"),
    ColorRampStop(0.55, "#74c476", (116, 196, 118), "Moderate"),
    ColorRampStop(0.85, "#238443", (35, 132, 67), "Dense Canopy"),
)

EVI_RAMP: tuple[ColorRampStop, ...] = (
    ColorRampStop(0.0, "#e5cbb0", (229, 203, 176), "Sparse"),
    ColorRampStop(0.22, "#dce4c2", (220, 228, 194), "Moderate"),
    ColorRampStop(0.45, "#8ec7be", (142, 199, 190), "Vigorous"),
    ColorRampStop(0.7, "#0e7c74", (14, 124, 116), "Dense"),
)

THERMAL_TREND_RAMP: tuple[ColorRampStop, ...] = (
    ColorRampStop(-0.4, "#3193ce", (49, 147, 206), "Cooling"),
    ColorRampStop(0.0, "#a4cfca", (164, 207, 202), "Neutral"),
    ColorRampStop(0.2, "#e8e9db", (232, 233, 219), "Mild"),
    ColorRampStop(0.44, "#deb49f", (222, 180, 159), "Elevated"),
    ColorRampStop(0.8, "#c77f6d", (199, 127, 109), "Warming"),
)

THERMAL_ABS_RAMP: tuple[ColorRampStop, ...] = (
    ColorRampStop(-10, "#3193ce", (49, 147, 206), "Cold"),
    ColorRampStop(12, "#a4cfca", (164, 207, 202), "Temperate"),
    ColorRampStop(26, "#ead6bc", (234, 214, 188), "Warm"),
    ColorRampStop(45, "#c77f6d", (199, 127, 109), "Hot"),
)

PRECIP_ANOMALY_RAMP: tuple[ColorRampStop, ...] = (
    ColorRampStop(-35, "#c77f6d", (199, 127, 109), "Deficit"),
    ColorRampStop(-15, "#deb49f", (222, 180, 159), "Dry"),
    ColorRampStop(0, "#e6ecee", (230, 236, 238), "Normal"),
    ColorRampStop(15, "#91c6bc", (145, 198, 188), "Wet"),
    ColorRampStop(35, "#3193ce", (49, 147, 206), "Surplus"),
)

SOIL_MOISTURE_RAMP: tuple[ColorRampStop, ...] = (
    ColorRampStop(0.02, "#deb49f", (222, 180, 159), "Arid"),
    ColorRampStop(0.18, "#e8e9db", (232, 233, 219), "Low"),
    ColorRampStop(0.34, "#91c6bc", (145, 198, 188), "Moist"),
    ColorRampStop(0.55, "#3193ce", (49, 147, 206), "Saturated"),
)

DIVERGING_ANOMALY_RAMP: tuple[ColorRampStop, ...] = (
    ColorRampStop(-2.5, "#c77f6d", (199, 127, 109), "Negative"),
    ColorRampStop(0, "#e8eef0", (232, 238, 240), "Baseline"),
    ColorRampStop(2.5, "#159b91", (21, 155, 145), "Positive"),
)

RESILIENCE_RAMP: tuple[ColorRampStop, ...] = (
    ColorRampStop(0, "#c77f6d", (199, 127, 109), "Low"),
    ColorRampStop(50, "#ead6bc", (234, 214, 188), "Moderate"),
    ColorRampStop(100, "#159b91", (21, 155, 145), "High"),
)
