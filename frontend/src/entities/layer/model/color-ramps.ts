export const VEGETATION_RAMP = [
  { value: 0.0, color: '#dfb892', rgb: [223, 184, 146] as [number, number, number], label: 'Bare / Sparse' },
  { value: 0.25, color: '#e7dfba', rgb: [231, 223, 186] as [number, number, number], label: 'Low' },
  { value: 0.55, color: '#a2d4b4', rgb: [162, 212, 180] as [number, number, number], label: 'Moderate' },
  { value: 0.85, color: '#159b91', rgb: [21, 155, 145] as [number, number, number], label: 'Dense Canopy' },
] as const

export const EVI_RAMP = [
  { value: 0.0, color: '#e5cbb0', rgb: [229, 203, 176] as [number, number, number], label: 'Sparse' },
  { value: 0.22, color: '#dce4c2', rgb: [220, 228, 194] as [number, number, number], label: 'Moderate' },
  { value: 0.45, color: '#8ec7be', rgb: [142, 199, 190] as [number, number, number], label: 'Vigorous' },
  { value: 0.7, color: '#0e7c74', rgb: [14, 124, 116] as [number, number, number], label: 'Dense' },
] as const

export const THERMAL_TREND_RAMP = [
  { value: -0.4, color: '#3193ce', rgb: [49, 147, 206] as [number, number, number], label: 'Cooling' },
  { value: 0.0, color: '#a4cfca', rgb: [164, 207, 202] as [number, number, number], label: 'Neutral' },
  { value: 0.2, color: '#e8e9db', rgb: [232, 233, 219] as [number, number, number], label: 'Mild' },
  { value: 0.44, color: '#deb49f', rgb: [222, 180, 159] as [number, number, number], label: 'Elevated' },
  { value: 0.8, color: '#c77f6d', rgb: [199, 127, 109] as [number, number, number], label: 'Warming' },
] as const

export const THERMAL_ABS_RAMP = [
  { value: -10, color: '#3193ce', rgb: [49, 147, 206] as [number, number, number], label: 'Cold' },
  { value: 12, color: '#a4cfca', rgb: [164, 207, 202] as [number, number, number], label: 'Temperate' },
  { value: 26, color: '#ead6bc', rgb: [234, 214, 188] as [number, number, number], label: 'Warm' },
  { value: 45, color: '#c77f6d', rgb: [199, 127, 109] as [number, number, number], label: 'Hot' },
] as const

export const PRECIP_ANOMALY_RAMP = [
  { value: -35, color: '#c77f6d', rgb: [199, 127, 109] as [number, number, number], label: 'Deficit' },
  { value: -15, color: '#deb49f', rgb: [222, 180, 159] as [number, number, number], label: 'Dry' },
  { value: 0, color: '#e6ecee', rgb: [230, 236, 238] as [number, number, number], label: 'Normal' },
  { value: 15, color: '#91c6bc', rgb: [145, 198, 188] as [number, number, number], label: 'Wet' },
  { value: 35, color: '#3193ce', rgb: [49, 147, 206] as [number, number, number], label: 'Surplus' },
] as const

export const SOIL_MOISTURE_RAMP = [
  { value: 0.02, color: '#deb49f', rgb: [222, 180, 159] as [number, number, number], label: 'Arid' },
  { value: 0.18, color: '#e8e9db', rgb: [232, 233, 219] as [number, number, number], label: 'Low' },
  { value: 0.34, color: '#91c6bc', rgb: [145, 198, 188] as [number, number, number], label: 'Moist' },
  { value: 0.55, color: '#3193ce', rgb: [49, 147, 206] as [number, number, number], label: 'Saturated' },
] as const

export const DIVERGING_ANOMALY_RAMP = [
  { value: -2.5, color: '#c77f6d', rgb: [199, 127, 109] as [number, number, number], label: 'Negative' },
  { value: 0, color: '#e8eef0', rgb: [232, 238, 240] as [number, number, number], label: 'Baseline' },
  { value: 2.5, color: '#159b91', rgb: [21, 155, 145] as [number, number, number], label: 'Positive' },
] as const

export const RESILIENCE_RAMP = [
  { value: 0, color: '#c77f6d', rgb: [199, 127, 109] as [number, number, number], label: 'Low' },
  { value: 50, color: '#ead6bc', rgb: [234, 214, 188] as [number, number, number], label: 'Moderate' },
  { value: 100, color: '#159b91', rgb: [21, 155, 145] as [number, number, number], label: 'High' },
] as const
