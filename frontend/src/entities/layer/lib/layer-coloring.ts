import type { MapLayerDefinition } from '../../../shared/types/geospatial'

export function interpolateColorFromLayer(
  layer: MapLayerDefinition,
  rawValue: number | null | undefined,
  customMin?: number,
  customMax?: number,
): string {
  if (rawValue === null || rawValue === undefined || Number.isNaN(rawValue)) {
    return layer.legend.nodataColor
  }

  const minBound = customMin ?? layer.valueRange.defaultMin
  const maxBound = customMax ?? layer.valueRange.defaultMax
  const clamped = Math.max(minBound, Math.min(maxBound, rawValue))

  const stops = layer.colorRamp
  if (stops.length === 0) {
    return layer.legend.nodataColor
  }

  const domainMin = stops[0].value
  const domainMax = stops[stops.length - 1].value
  const normalizedInput =
    maxBound > minBound
      ? domainMin + ((clamped - minBound) / (maxBound - minBound)) * (domainMax - domainMin)
      : domainMin

  if (normalizedInput <= stops[0].value) {
    return stops[0].color
  }
  const lastStop = stops[stops.length - 1]
  if (normalizedInput >= lastStop.value) {
    return lastStop.color
  }

  for (let i = 0; i < stops.length - 1; i++) {
    const start = stops[i]
    const end = stops[i + 1]
    if (normalizedInput >= start.value && normalizedInput <= end.value) {
      const span = end.value - start.value
      const t = span > 0 ? (normalizedInput - start.value) / span : 0
      const r = Math.round(start.rgb[0] + (end.rgb[0] - start.rgb[0]) * t)
      const g = Math.round(start.rgb[1] + (end.rgb[1] - start.rgb[1]) * t)
      const b = Math.round(start.rgb[2] + (end.rgb[2] - start.rgb[2]) * t)
      return `rgb(${r}, ${g}, ${b})`
    }
  }

  return lastStop.color
}
