import { useEffect, useMemo } from 'react'
import { useLayerCatalogQuery, useTemporalCoverageQuery } from '../../../shared/api/layers'
import { BASEMAP_PROVIDER_REGISTRY } from '../../../shared/config/geospatial'
import type { ObservationGranularity } from '../../../shared/types/geospatial'
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Pause,
  Play,
} from '../../../shared/ui/explorer-icons'
import { resolveLayerControlState, useExploreStore } from '../model/use-explore-store'

function stepIsoDate(isoDate: string, cadence: ObservationGranularity, dir: 1 | -1): string {
  const parsed = new Date(`${isoDate}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return isoDate
  if (cadence === 'daily' || cadence === '30-minute') {
    parsed.setUTCDate(parsed.getUTCDate() + dir)
  } else if (cadence === '8-day') {
    parsed.setUTCDate(parsed.getUTCDate() + 8 * dir)
  } else if (cadence === '16-day') {
    parsed.setUTCDate(parsed.getUTCDate() + 16 * dir)
  } else if (cadence === 'multi-year') {
    parsed.setUTCFullYear(parsed.getUTCFullYear() + dir)
  } else {
    parsed.setUTCMonth(parsed.getUTCMonth() + dir)
  }
  return parsed.toISOString().slice(0, 10)
}

function dateToMs(isoDate: string): number {
  const t = Date.parse(`${isoDate}T00:00:00Z`)
  return Number.isNaN(t) ? Date.parse('2025-12-01T00:00:00Z') : t
}

export function TemporalLegendBar() {
  const bottomPanelOpen = useExploreStore((s) => s.bottomPanelOpen)
  const setBottomPanelOpen = useExploreStore((s) => s.setBottomPanelOpen)
  const primaryLayerId = useExploreStore((s) => s.primaryLayerId)
  const layerStates = useExploreStore((s) => s.layerStates)
  const basemap = useExploreStore((s) => s.basemap)
  const selectedDate = useExploreStore((s) => s.selectedDate)
  const setSelectedDate = useExploreStore((s) => s.setSelectedDate)
  const dateRangeStart = useExploreStore((s) => s.dateRangeStart)
  const dateRangeEnd = useExploreStore((s) => s.dateRangeEnd)
  const setDateRange = useExploreStore((s) => s.setDateRange)
  const temporalPlaying = useExploreStore((s) => s.temporalPlaying)
  const setTemporalPlaying = useExploreStore((s) => s.setTemporalPlaying)
  const toggleTemporalPlaying = useExploreStore((s) => s.toggleTemporalPlaying)

  const catalogQuery = useLayerCatalogQuery()
  const layers = catalogQuery.data ?? []
  const activeLayer = layers.find((layer) => layer.id === primaryLayerId) ?? layers[0] ?? null
  const basemapConfig = BASEMAP_PROVIDER_REGISTRY[basemap]
  const coverageQuery = useTemporalCoverageQuery(activeLayer?.id ?? '', Boolean(activeLayer))
  const cadence: ObservationGranularity = activeLayer?.availableTimeRange.cadence ?? 'monthly'
  const availableDates = useMemo(
    () => activeLayer?.availableDates ?? [],
    [activeLayer?.availableDates],
  )

  useEffect(() => {
    if (!temporalPlaying || !activeLayer) return
    const timer = window.setInterval(() => {
      const current = useExploreStore.getState().selectedDate
      if (availableDates.length > 0) {
        const idx = availableDates.indexOf(current)
        const nextIdx = idx >= 0 && idx + 1 < availableDates.length ? idx + 1 : 0
        setSelectedDate(availableDates[nextIdx])
        return
      }
      const next = stepIsoDate(current, cadence, 1)
      if (next > dateRangeEnd) {
        setSelectedDate(dateRangeStart)
      } else {
        setSelectedDate(next)
      }
    }, 950)
    return () => window.clearInterval(timer)
  }, [activeLayer, availableDates, cadence, dateRangeEnd, dateRangeStart, setSelectedDate, temporalPlaying])

  const rangeMinMs = useMemo(() => dateToMs(dateRangeStart), [dateRangeStart])
  const rangeMaxMs = useMemo(
    () => Math.max(rangeMinMs + 86_400_000, dateToMs(dateRangeEnd)),
    [dateRangeEnd, rangeMinMs],
  )
  const currentMs = useMemo(() => {
    const val = dateToMs(selectedDate)
    return Math.min(rangeMaxMs, Math.max(rangeMinMs, val))
  }, [rangeMaxMs, rangeMinMs, selectedDate])

  if (!bottomPanelOpen) {
    return (
      <div className="explorer-bottom-collapsed">
        <span className="explorer-bottom-collapsed__meta">
          {activeLayer ? activeLayer.shortName : 'Layer catalog'} · {selectedDate} · {basemapConfig.shortName}
        </span>
        <button
          type="button"
          className="explorer-icon-btn"
          onClick={() => setBottomPanelOpen(true)}
        >
          <ChevronUp size={14} />
          <span>Timeline &amp; Legend</span>
        </button>
      </div>
    )
  }

  const activeControl = activeLayer
    ? resolveLayerControlState(activeLayer, layerStates[activeLayer.id], primaryLayerId)
    : null
  const minDisplay = activeControl?.minValue ?? 0
  const maxDisplay = activeControl?.maxValue ?? 1
  const midDisplay = Number(((minDisplay + maxDisplay) / 2).toFixed(2))

  return (
    <section
      className="explorer-bottom-dock"
      aria-label="Temporal controls, map legend, and attribution"
    >
      <div className="explorer-temporal-pane">
        <div className="explorer-temporal-row">
          <div className="explorer-temporal-controls">
            <button
              type="button"
              className="explorer-icon-mini"
              disabled={!activeLayer}
              onClick={() => {
                setTemporalPlaying(false)
                if (availableDates.length > 0) {
                  const idx = availableDates.indexOf(selectedDate)
                  const targetIdx = idx > 0 ? idx - 1 : 0
                  setSelectedDate(availableDates[targetIdx])
                  return
                }
                const prev = stepIsoDate(selectedDate, cadence, -1)
                setSelectedDate(prev < dateRangeStart ? dateRangeStart : prev)
              }}
              aria-label="Previous observation step"
              title="Previous observation step"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              type="button"
              className={`explorer-icon-mini ${temporalPlaying ? 'is-active' : ''}`}
              disabled={!activeLayer}
              onClick={toggleTemporalPlaying}
              aria-label={temporalPlaying ? 'Pause timeline' : 'Play timeline'}
              title={temporalPlaying ? 'Pause' : 'Play observation timeline'}
            >
              {temporalPlaying ? <Pause size={13} /> : <Play size={13} />}
            </button>
            <button
              type="button"
              className="explorer-icon-mini"
              disabled={!activeLayer}
              onClick={() => {
                setTemporalPlaying(false)
                if (availableDates.length > 0) {
                  const idx = availableDates.indexOf(selectedDate)
                  const targetIdx =
                    idx >= 0 && idx + 1 < availableDates.length
                      ? idx + 1
                      : availableDates.length - 1
                  setSelectedDate(availableDates[targetIdx])
                  return
                }
                const next = stepIsoDate(selectedDate, cadence, 1)
                setSelectedDate(next > dateRangeEnd ? dateRangeEnd : next)
              }}
              aria-label="Next observation step"
              title="Next observation step"
            >
              <ChevronRight size={14} />
            </button>
          </div>

          <input
            type="range"
            className="explorer-timeline-slider"
            min={rangeMinMs}
            max={rangeMaxMs}
            step={86_400_000}
            value={currentMs}
            onChange={(e) => {
              const iso = new Date(Number(e.target.value)).toISOString().slice(0, 10)
              setSelectedDate(iso)
            }}
            aria-label="Observation date timeline slider"
          />

          <div className="explorer-date-bounds">
            <input
              type="date"
              className="explorer-mini-date"
              value={dateRangeStart}
              min={activeLayer?.availableTimeRange.start ?? '2000-01-01'}
              max={dateRangeEnd}
              onChange={(e) => {
                if (e.target.value) setDateRange(e.target.value, dateRangeEnd)
              }}
              aria-label="Range start date"
            />
            <span aria-hidden="true">-</span>
            <input
              type="date"
              className="explorer-mini-date"
              value={dateRangeEnd}
              min={dateRangeStart}
              max={activeLayer?.availableTimeRange.end ?? '2030-12-31'}
              onChange={(e) => {
                if (e.target.value) setDateRange(dateRangeStart, e.target.value)
              }}
              aria-label="Range end date"
            />
          </div>
        </div>

        <div className="explorer-coverage-strip">
          <span>
            Target date: <strong>{selectedDate}</strong> ({cadence})
          </span>
          {availableDates.length > 0 && (
            <label className="explorer-select-wrap">
              <span className="explorer-sr-only">Ingested observation date</span>
              <select
                className="explorer-mini-select"
                value={availableDates.includes(selectedDate) ? selectedDate : availableDates[availableDates.length - 1]}
                onChange={(e) => setSelectedDate(e.target.value)}
                aria-label="Select ingested observation date"
              >
                {availableDates.map((dateStr) => (
                  <option key={dateStr} value={dateStr}>
                    {dateStr}
                  </option>
                ))}
              </select>
            </label>
          )}
          {coverageQuery.data && (
            <span>
              Catalog window: {coverageQuery.data.startDate} to {coverageQuery.data.endDate} ·{' '}
              {availableDates.length > 0
                ? `${availableDates.length} ingested observation date(s)`
                : coverageQuery.data.isSimulatedCoverage
                  ? 'no ingested observations available'
                  : `${coverageQuery.data.coveragePercent}% coverage`}
            </span>
          )}
        </div>
      </div>

      <div className="explorer-legend-pane">
        {!activeLayer ? (
          <>
            <div className="explorer-legend-pane__head">
              <div className="explorer-legend-pane__title-wrap">
                <span className="explorer-legend-pane__title">
                  {catalogQuery.isPending ? 'Loading layer legend…' : 'Layer legend unavailable'}
                </span>
                {catalogQuery.isError && (
                  <button
                    type="button"
                    className="explorer-inline-reset"
                    onClick={() => void catalogQuery.refetch()}
                  >
                    Retry API
                  </button>
                )}
              </div>
              <button
                type="button"
                className="explorer-icon-mini"
                onClick={() => setBottomPanelOpen(false)}
                aria-label="Collapse bottom timeline and legend bar"
                title="Collapse bar"
              >
                <ChevronDown size={14} />
              </button>
            </div>
            <div className="explorer-attribution-line">
              <span>Basemap: {basemapConfig.attribution}</span>
              <span>Layer: TERRA Core API /api/v1/layers not connected</span>
            </div>
          </>
        ) : (
          <>
            <div className="explorer-legend-pane__head">
              <div className="explorer-legend-pane__title-wrap">
                <span className="explorer-legend-pane__title">{activeLayer.legend.title}</span>
                <span className="explorer-legend-pane__unit">({activeLayer.legend.unit})</span>
                {activeLayer.availabilityStatus === 'connected' ? (
                  <span className="explorer-status-pill is-connected">
                    Connected Raster · Nearest
                  </span>
                ) : (
                  <span
                    className="explorer-status-pill is-unavailable"
                    title={activeLayer.unavailableReason ?? undefined}
                  >
                    {activeLayer.unavailableReason ?? 'Unavailable · Not ingested'}
                  </span>
                )}
              </div>

              <button
                type="button"
                className="explorer-icon-mini"
                onClick={() => setBottomPanelOpen(false)}
                aria-label="Collapse bottom timeline and legend bar"
                title="Collapse bar"
              >
                <ChevronDown size={14} />
              </button>
            </div>

            <div className="explorer-legend-bar-wrap">
              <div
                className="explorer-legend-gradient"
                style={{ background: activeLayer.legend.gradientCss }}
              />
              <div className="explorer-legend-ticks">
                <span>{minDisplay}</span>
                <span>{midDisplay}</span>
                <span>{maxDisplay}</span>
              </div>
              <div className="explorer-nodata-chip">
                <span
                  className="explorer-nodata-swatch"
                  style={{ backgroundColor: activeLayer.legend.nodataColor }}
                />
                <span>{activeLayer.legend.nodataLabel}</span>
              </div>
            </div>

            <div className="explorer-attribution-line">
              <span>Basemap: {basemapConfig.attribution}</span>
              <span>Layer: {activeLayer.attribution}</span>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
