import { useEffect, useMemo } from 'react'
import { useLayerCatalogQuery, useTemporalCoverageQuery } from '../../../shared/api/layers'
import { BASEMAP_PROVIDER_REGISTRY } from '../../../shared/config/geospatial'
import { buildGibsMapLayer, findLiveLayer } from '../../../shared/config/live-environment'
import { getMaxSelectableDateIso } from '../../../shared/lib/date'
import type { ObservationGranularity } from '../../../shared/types/geospatial'
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Pause,
  Play,
} from '../../../shared/ui/explorer-icons'
import {
  computeTimelineSliderState,
  dayIndexToIsoDate,
  stepIsoDate,
  stepTimelineDate,
} from '../lib/timeline'
import { resolveLayerControlState, useExploreStore } from '../model/use-explore-store'

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

  const gibsLayerId = useExploreStore((s) => s.gibsLayerId)
  const gibsDate = useExploreStore((s) => s.gibsDate)
  const setGibsDate = useExploreStore((s) => s.setGibsDate)
  const catalogQuery = useLayerCatalogQuery()
  const layers = catalogQuery.data ?? []
  const liveLayer = findLiveLayer(gibsLayerId)
  const liveMapLayer = liveLayer ? buildGibsMapLayer(liveLayer, gibsDate) : null
  const activeLayer = liveMapLayer ?? layers.find((layer) => layer.id === primaryLayerId) ?? layers[0] ?? null
  const basemapConfig = BASEMAP_PROVIDER_REGISTRY[basemap]
  const coverageQuery = useTemporalCoverageQuery(
    activeLayer?.id ?? '',
    Boolean(activeLayer) && !liveMapLayer,
  )
  const cadence: ObservationGranularity = activeLayer?.availableTimeRange.cadence ?? 'monthly'
  const availableDates = useMemo(
    () => (liveMapLayer ? [] : (activeLayer?.availableDates ?? [])),
    [activeLayer?.availableDates, liveMapLayer],
  )
  const displayDate = liveMapLayer ? gibsDate : selectedDate
  const maxSelectableDate = getMaxSelectableDateIso()
  const sliderState = useMemo(
    () =>
      computeTimelineSliderState({
        dateRangeStart,
        dateRangeEnd,
        displayDate,
        maxSelectableDate,
      }),
    [dateRangeEnd, dateRangeStart, displayDate, maxSelectableDate],
  )

  useEffect(() => {
    if (!temporalPlaying || !activeLayer) return
    const timer = window.setInterval(() => {
      const store = useExploreStore.getState()
      const current = store.gibsLayerId ? store.gibsDate : store.selectedDate
      const next = stepIsoDate(current, cadence, 1)
      const target = next > sliderState.effectiveRangeEnd ? dateRangeStart : next
      setSelectedDate(target)
      if (store.gibsLayerId) setGibsDate(target)
    }, 950)
    return () => window.clearInterval(timer)
  }, [
    activeLayer,
    cadence,
    dateRangeStart,
    setGibsDate,
    setSelectedDate,
    sliderState.effectiveRangeEnd,
    temporalPlaying,
  ])

  if (!bottomPanelOpen) {
    return (
      <div className="explorer-bottom-collapsed">
        <span className="explorer-bottom-collapsed__meta">
          {activeLayer ? activeLayer.shortName : 'Layer catalog'} · {displayDate} · {basemapConfig.shortName}
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

  const rangeEndMax =
    activeLayer?.availableTimeRange.end && activeLayer.availableTimeRange.end > maxSelectableDate
      ? activeLayer.availableTimeRange.end
      : maxSelectableDate

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
                const target = stepTimelineDate({
                  currentDate: displayDate,
                  cadence,
                  direction: -1,
                  minDate: dateRangeStart,
                  maxDate: sliderState.effectiveRangeEnd,
                })
                setSelectedDate(target)
                if (liveMapLayer) setGibsDate(target)
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
                const target = stepTimelineDate({
                  currentDate: displayDate,
                  cadence,
                  direction: 1,
                  minDate: dateRangeStart,
                  maxDate: sliderState.effectiveRangeEnd,
                })
                setSelectedDate(target)
                if (liveMapLayer) setGibsDate(target)
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
            min={sliderState.min}
            max={sliderState.max}
            step={1}
            value={sliderState.value}
            onChange={(e) => {
              const iso = dayIndexToIsoDate(sliderState.rangeMinMs, Number(e.target.value))
              setSelectedDate(iso)
              if (liveMapLayer) setGibsDate(iso)
            }}
            aria-label="Observation date timeline slider"
          />

          <div className="explorer-date-bounds">
            <input
              type="date"
              className="explorer-mini-date"
              value={dateRangeStart}
              min={activeLayer?.availableTimeRange.start ?? '2000-01-01'}
              max={sliderState.effectiveRangeEnd}
              onChange={(e) => {
                if (e.target.value) setDateRange(e.target.value, sliderState.effectiveRangeEnd)
              }}
              aria-label="Range start date"
            />
            <span aria-hidden="true">-</span>
            <input
              type="date"
              className="explorer-mini-date"
              value={sliderState.effectiveRangeEnd}
              min={dateRangeStart}
              max={rangeEndMax}
              onChange={(e) => {
                if (e.target.value) setDateRange(dateRangeStart, e.target.value)
              }}
              aria-label="Range end date"
            />
          </div>
        </div>

        <div className="explorer-coverage-strip">
          <span>
            Target date: <strong>{displayDate}</strong> ({cadence})
          </span>
          {availableDates.length > 0 && (
            <label className="explorer-select-wrap">
              <span className="explorer-sr-only">Ingested observation date</span>
              <select
                className="explorer-mini-select"
                value={availableDates.includes(selectedDate) ? selectedDate : ''}
                onChange={(e) => {
                  if (!e.target.value) return
                  setSelectedDate(e.target.value)
                }}
                aria-label="Select ingested observation date"
              >
                {!availableDates.includes(selectedDate) && (
                  <option value="" disabled>
                    Ingested ({availableDates.length})
                  </option>
                )}
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
                {activeLayer.availabilityStatus === 'connected' ||
                (activeLayer.availabilityStatus === 'preview' && activeLayer.tileSource.isConnected) ? (
                  <span
                    className={`explorer-status-pill ${
                      activeLayer.availabilityStatus === 'preview' ? 'is-preview' : 'is-connected'
                    }`}
                  >
                    {activeLayer.availabilityStatus === 'preview'
                      ? 'AOI Preview · Nearest'
                      : 'Connected Raster · Nearest'}
                  </span>
                ) : (
                  <span
                    className={`explorer-status-pill ${
                      activeLayer.availabilityStatus === 'planned' ? 'is-planned' : 'is-unavailable'
                    }`}
                    title={activeLayer.unavailableReason ?? undefined}
                  >
                    {activeLayer.unavailableReason ??
                      (activeLayer.availabilityStatus === 'planned'
                        ? 'Planned · Not yet ingested'
                        : 'Unavailable · Not ingested')}
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
