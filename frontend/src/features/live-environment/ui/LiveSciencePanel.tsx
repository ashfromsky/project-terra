import { useMemo, useState } from 'react'
import {
  MODIS_NDVI_ASSET,
  MODIS_NDVI_COLLECTION,
  POWER_PARAMETERS,
  findLiveLayer,
  type PowerParameter,
} from '../../../shared/config/live-environment'
import { buildMonthlyAnomalyOption, buildTimeSeriesChartOption } from '../../../shared/lib/scientific-charts'
import type { AoiGeometry } from '../../../shared/types/geospatial'
import { Chart } from '../../../shared/ui/chart'
import { useAoiWorkspace } from '../../map-explorer/model/use-aoi-workspace'
import { useExploreStore } from '../../map-explorer/model/use-explore-store'
import type { ModisSeriesPoint, LiveAoiGeometry } from '../lib/cog'
import { formatNumber } from '../lib/stats'
import { useScienceWorker } from '../model/use-science-worker'
import type {
  ModisSeriesScienceResult,
  PowerScienceResult,
  ScienceResult,
} from '../model/science-types'

function toLiveGeometry(geometry: AoiGeometry): LiveAoiGeometry {
  if (geometry.type === 'Polygon') {
    return {
      type: 'Polygon',
      coordinates: geometry.coordinates.map((ring) => ring.map(([lon, lat]) => [lon, lat])),
    }
  }
  return {
    type: 'MultiPolygon',
    coordinates: geometry.coordinates.map((polygon) =>
      polygon.map((ring) => ring.map(([lon, lat]) => [lon, lat])),
    ),
  }
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

function StatsTable({ stats, unit }: { stats: { validCount: number; missingCount: number; mean: number | null; median: number | null; min: number | null; max: number | null; standardDeviation: number | null; p10: number | null; p90: number | null }; unit: string }) {
  return (
    <dl className="explorer-kv-list explorer-kv-list--dense live-science-stats">
      <StatRow label="Valid / missing" value={`${stats.validCount} / ${stats.missingCount}`} />
      <StatRow label="Mean" value={`${formatNumber(stats.mean)} ${unit}`} />
      <StatRow label="Median" value={`${formatNumber(stats.median)} ${unit}`} />
      <StatRow label="Min / max" value={`${formatNumber(stats.min)} / ${formatNumber(stats.max)}`} />
      <StatRow label="Std. deviation" value={formatNumber(stats.standardDeviation)} />
      <StatRow label="P10 / P90" value={`${formatNumber(stats.p10)} / ${formatNumber(stats.p90)}`} />
    </dl>
  )
}

function PowerResult({ result }: { result: PowerScienceResult }) {
  const series = result.data.series.find((item) => item.label === result.variable) ?? result.data.series[0]
  const chartOption = useMemo(
    () =>
      buildTimeSeriesChartOption({
        title: `NASA POWER · ${result.variable}`,
        variableName: result.variable,
        units: result.unit,
        timestamps: series.timestamps,
        values: series.values,
        color: '#159b91',
      }),
    [result.unit, result.variable, series.timestamps, series.values],
  )
  const anomalyOption = useMemo(
    () =>
      buildMonthlyAnomalyOption({
        title: 'Standardized monthly anomalies',
        variableName: result.variable,
        timestamps: result.anomalies.timestamps,
        anomalies: result.anomalies.anomalies,
      }),
    [result.anomalies.anomalies, result.anomalies.timestamps, result.variable],
  )
  return (
    <div className="live-science-result">
      <div className="live-science-result__head">
        <div>
          <span className="explorer-overline">NASA POWER · monthly point</span>
          <h4>{result.variable} ({result.unit})</h4>
        </div>
        <span className="explorer-status-pill is-connected">calculated</span>
      </div>
      <p className="explorer-muted-copy">
        {result.data.latitude.toFixed(4)}°, {result.data.longitude.toFixed(4)}° ·{' '}
        {result.data.startYear}–{result.data.endYear}
      </p>
      <StatsTable stats={result.stats} unit={result.unit} />
      <div className="live-science-trend">
        <strong>Mann–Kendall</strong>
        <span>
          {result.trend.mannKendall.direction.replace('_', ' ')} · p ={' '}
          {formatNumber(result.trend.mannKendall.pValue, 4)} · n ={' '}
          {result.trend.mannKendall.sampleCount}
        </span>
        <strong>Theil–Sen</strong>
        <span>
          {formatNumber(result.trend.senSlope.slopePerYear)} {result.trend.senSlope.unit} · 95% CI{' '}
          {formatNumber(result.trend.senSlope.ciLow)} … {formatNumber(result.trend.senSlope.ciHigh)}
        </span>
      </div>
      <Chart option={chartOption} className="live-science-chart" />
      <Chart option={anomalyOption} className="live-science-chart live-science-chart--short" />
      <p className="explorer-resolution-note">{result.data.note}</p>
      <p className="explorer-resolution-note">{result.trend.mannKendall.note}</p>
      <details className="live-science-limits">
        <summary>Scientific limitations</summary>
        <ul>
          {result.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function ModisResult({ result }: { result: ModisSeriesScienceResult }) {
  const timestamps = result.points.map((point: ModisSeriesPoint) => point.timestamp)
  const values = result.points.map((point) => point.mean)
  const chartOption = useMemo(
    () =>
      buildTimeSeriesChartOption({
        title: 'MODIS NDVI · AOI composites',
        variableName: 'NDVI',
        units: result.unit,
        timestamps,
        values,
        color: '#2f8f6b',
      }),
    [result.unit, timestamps, values],
  )
  return (
    <div className="live-science-result">
      <div className="live-science-result__head">
        <div>
          <span className="explorer-overline">Planetary Computer · MODIS COG</span>
          <h4>NDVI AOI statistics</h4>
        </div>
        <span className="explorer-status-pill is-connected">calculated</span>
      </div>
      <p className="explorer-muted-copy">
        {result.points.length} composites · {result.collection} · browser range reads only
      </p>
      <StatsTable stats={result.stats} unit={result.unit} />
      <div className="live-science-trend">
        <strong>Mann–Kendall</strong>
        <span>
          {result.trend.mannKendall.direction.replace('_', ' ')} · p ={' '}
          {formatNumber(result.trend.mannKendall.pValue, 4)} · n ={' '}
          {result.trend.mannKendall.sampleCount}
        </span>
        <strong>Theil–Sen</strong>
        <span>
          {formatNumber(result.trend.senSlope.slopePerYear)} {result.trend.senSlope.unit} · 95% CI{' '}
          {formatNumber(result.trend.senSlope.ciLow)} … {formatNumber(result.trend.senSlope.ciHigh)}
        </span>
      </div>
      <Chart option={chartOption} className="live-science-chart" />
      <div className="live-science-series">
        {result.points.map((point) => (
          <div key={point.itemId}>
            <span>{point.timestamp.slice(0, 10)}</span>
            <span>
              {formatNumber(point.mean)} {result.unit}
            </span>
            <span>
              {point.validPixelCount}/{point.maskedPixelCount} px
            </span>
          </div>
        ))}
      </div>
      <p className="explorer-resolution-note">{result.trend.senSlope.note}</p>
      <details className="live-science-limits">
        <summary>Scientific limitations</summary>
        <ul>
          {result.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}

export function LiveSciencePanel() {
  const { selectedAoi } = useAoiWorkspace()
  const inspectedPoint = useExploreStore((s) => s.inspectedPoint)
  const gibsLayerId = useExploreStore((s) => s.gibsLayerId)
  const liveLayer = findLiveLayer(gibsLayerId)
  const [startDate, setStartDate] = useState('2024-01-01')
  const [endDate, setEndDate] = useState('2024-12-31')
  const [powerVariable, setPowerVariable] = useState<PowerParameter>('T2M')
  const [error, setError] = useState<string | null>(null)
  const worker = useScienceWorker()

  const point = useMemo(() => {
    if (inspectedPoint) return inspectedPoint
    if (selectedAoi) {
      return { lon: selectedAoi.properties.centroid[0], lat: selectedAoi.properties.centroid[1] }
    }
    return null
  }, [inspectedPoint, selectedAoi])

  const runPower = () => {
    setError(null)
    if (!point) {
      setError('Select an AOI or inspect a point on the map first.')
      return
    }
    worker.run({
      kind: 'power',
      latitude: point.lat,
      longitude: point.lon,
      startDate,
      endDate,
      variable: powerVariable,
    })
  }

  const runModis = () => {
    setError(null)
    if (!selectedAoi) {
      setError('Draw or select a saved AOI before running MODIS AOI statistics.')
      return
    }
    worker.run({
      kind: 'modis-series',
      collection: MODIS_NDVI_COLLECTION,
      assetKey: MODIS_NDVI_ASSET,
      bbox: selectedAoi.properties.bbox,
      geometry: toLiveGeometry(selectedAoi.geometry),
      startDate,
      endDate,
      variable: 'NDVI',
      unit: 'NDVI',
      fallbackScale: 0.0001,
      fallbackNodata: -3000,
      maxItems: 12,
    })
  }

  const result: ScienceResult | null = worker.result

  return (
    <div className="explorer-inspector-stack" role="tabpanel">
      <section className="explorer-inspector-card live-science-card">
        <div className="live-science-head">
          <div>
            <span className="explorer-overline">Client-side science</span>
            <h3>Live environmental calculations</h3>
          </div>
          <span className="explorer-status-pill is-connected">browser only</span>
        </div>
        <p className="explorer-muted-copy">
          Calculations run in a Web Worker in this browser. NASA POWER and Planetary Computer
          requests go directly from the browser; no raster is uploaded to or persisted by TERRA.
        </p>

        <div className="explorer-analysis-grid">
          <label className="explorer-analysis-field" htmlFor="live-start">
            <span>Start</span>
            <input
              id="live-start"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </label>
          <label className="explorer-analysis-field" htmlFor="live-end">
            <span>End</span>
            <input
              id="live-end"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </label>
        </div>

        <div className="live-science-section">
          <div className="live-science-section__head">
            <strong>Point meteorology</strong>
            <span>NASA POWER · monthly</span>
          </div>
          <label className="explorer-analysis-field" htmlFor="live-power-variable">
            <span>Variable</span>
            <select
              id="live-power-variable"
              value={powerVariable}
              onChange={(e) => setPowerVariable(e.target.value as PowerParameter)}
            >
              {Object.entries(POWER_PARAMETERS).map(([key, meta]) => (
                <option key={key} value={key}>
                  {meta.label} ({meta.unit})
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="explorer-action-btn explorer-action-btn--primary"
            disabled={worker.status === 'running'}
            onClick={runPower}
          >
            Calculate POWER statistics
          </button>
          <p className="explorer-resolution-note">
            Point: {point ? `${point.lat.toFixed(4)}°, ${point.lon.toFixed(4)}°` : 'no AOI or inspected point'}
          </p>
        </div>

        <div className="live-science-section">
          <div className="live-science-section__head">
            <strong>MODIS NDVI AOI</strong>
            <span>MOD13Q1 · COG range reads</span>
          </div>
          <button
            type="button"
            className="explorer-action-btn"
            disabled={worker.status === 'running'}
            onClick={runModis}
          >
            Calculate NDVI series ({selectedAoi ? 'selected AOI' : 'no AOI'})
          </button>
          <p className="explorer-resolution-note">
            Reads at most 12 MODIS composites intersecting the AOI from Planetary Computer; values
            are scaled source pixels, not GIBS colours.
          </p>
        </div>

        {worker.status === 'running' ? (
          <div className="explorer-status-banner" role="status" aria-live="polite">
            <strong>Calculating in browser</strong>
            <p>{worker.message ?? 'Working…'}</p>
            {worker.progress ? (
              <p>
                {worker.progress.completed} / {worker.progress.total}
              </p>
            ) : null}
            <button type="button" className="explorer-inline-reset" onClick={worker.cancel}>
              Cancel
            </button>
          </div>
        ) : null}

        {error ? (
          <div className="explorer-status-banner is-error" role="alert">
            <strong>Cannot calculate</strong>
            <p>{error}</p>
          </div>
        ) : null}

        {worker.error ? (
          <div className="explorer-status-banner is-error" role="alert">
            <strong>Calculation failed</strong>
            <p>{worker.error}</p>
          </div>
        ) : null}

        {result?.kind === 'power' ? <PowerResult result={result} /> : null}
        {result?.kind === 'modis-series' ? <ModisResult result={result} /> : null}

        {liveLayer ? (
          <p className="explorer-resolution-note">
            Map layer <strong>{liveLayer.shortName}</strong> is a NASA GIBS visualization. It is
            not used as numerical input.
          </p>
        ) : null}
      </section>
    </div>
  )
}
