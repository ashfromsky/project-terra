export function buildSampleMod13InlineDataset(): Record<string, unknown>[] {
  const timestamps: string[] = []
  const values: number[] = []
  const qa: number[] = []

  for (let year = 2018; year <= 2024; year += 1) {
    for (let month = 1; month <= 12; month += 1) {
      const isoMonth = String(month).padStart(2, '0')
      timestamps.push(`${year}-${isoMonth}-01T00:00:00Z`)
      const seasonal = 0.16 * Math.sin((2 * Math.PI * (month - 1)) / 12)
      const shock = year === 2022 && month >= 6 && month <= 8 ? -0.22 : 0
      const base = 0.54 + seasonal + 0.006 * (year - 2018) + shock
      values.push(Number(base.toFixed(4)))
      qa.push(0)
    }
  }

  const meta = {
    name: 'NDVI',
    canonical_name: 'ndvi',
    units: 'dimensionless',
    semantic_kind: 'continuous_intensive',
    scale_factor: 0.0001,
    is_scaled: true,
    fill_values: [-3000.0],
    valid_range: [-0.2, 1.0],
  }

  return [
    {
      dataset_id: 'inline-mod13-test-input',
      source_id: 'modis_mod13q1',
      product: 'MOD13Q1.061',
      product_version: '061',
      provider: 'nasa_earthdata',
      spatial_support: { crs: 'EPSG:4326', nominal_resolution_m: 250.0 },
      temporal_metadata: {
        cadence: 'monthly',
        semantics: 'composite',
        composite_days: 16,
        start: timestamps[0],
        end: timestamps[timestamps.length - 1],
      },
      variables: { NDVI: meta },
      series: {
        NDVI: {
          timestamps,
          values,
          qa_layers: { pixel_reliability: qa },
          metadata: meta,
        },
      },
    },
  ]
}
