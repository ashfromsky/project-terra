import { figmaAssets } from '../../../shared/config/assets'
import type {
  CountrySelectionSummary,
  RegionOption,
  VariableOption,
} from '../../../shared/store/ui-store'
import type { MapLayerDefinition } from '../../../shared/types/geospatial'
import { THEMATIC_LAYER_METADATA } from '../config/map-style'
import { formatCalloutReadout } from '../lib/use-region-interaction'

export interface MapLegendCardProps {
  selectedVariable: VariableOption
  selectedRegion: RegionOption
  activeLayer: MapLayerDefinition | null
  selectedCountry: CountrySelectionSummary | null
  hoveredCountry: CountrySelectionSummary | null
  onClearSelectedCountry: () => void
}

export function MapLegendCard({
  selectedVariable,
  selectedRegion,
  activeLayer,
  selectedCountry,
  hoveredCountry,
  onClearSelectedCountry,
}: MapLegendCardProps) {
  const legendMeta = THEMATIC_LAYER_METADATA[selectedVariable]
  const activeCountry = hoveredCountry ?? selectedCountry
  const callout = formatCalloutReadout(
    selectedVariable,
    activeLayer,
    selectedRegion,
    activeCountry,
  )

  const dates = activeLayer?.availableDates ?? []
  const temporalSummary =
    dates.length > 0
      ? `${dates[0]} — ${dates[dates.length - 1]}`
      : activeLayer
        ? `${activeLayer.availableTimeRange.start} — ${activeLayer.availableTimeRange.end}`
        : 'Ingested COG'

  const rightAttribution =
    activeLayer?.availabilityStatus === 'connected'
      ? `${activeLayer.nativeSpatialResolution} · ${temporalSummary}`
      : 'Layer unavailable · No synthetic fallback'

  return (
    <>
      <div className="earth-observatory__callout" data-node-id="5:236">
        <div className="earth-observatory__callout-head">
          <p className="earth-observatory__callout-title" data-node-id="5:237">
            {callout.title}
          </p>
          {selectedCountry && (
            <button
              type="button"
              className="earth-observatory__callout-clear"
              onClick={onClearSelectedCountry}
              aria-label="Clear selected country"
            >
              ×
            </button>
          )}
        </div>
        <p className="earth-observatory__callout-value" data-node-id="5:238">
          {callout.valueLabel}
        </p>
        <p className="earth-observatory__callout-sig" data-node-id="5:239">
          {callout.subtitleLabel}
        </p>
      </div>

      <div className="earth-observatory__leader" data-node-id="5:240">
        <img src={figmaAssets.selectedRegionLeader} alt="" />
      </div>

      <div className="earth-observatory__legend" data-node-id="5:258">
        <p className="earth-observatory__legend-title" data-node-id="5:259">
          {activeLayer?.legend.title ?? legendMeta.shortTitle}
        </p>
        <p className="earth-observatory__legend-unit" data-node-id="5:260">
          {activeLayer?.legend.unit ?? legendMeta.unit}
        </p>
        <div
          className="earth-observatory__legend-bar"
          data-node-id="5:261"
          style={{
            background: activeLayer?.legend.gradientCss ?? legendMeta.gradientCss,
          }}
          aria-hidden="true"
        />
        <p className="earth-observatory__legend-min" data-node-id="5:262">
          {activeLayer?.legend.minLabel ?? legendMeta.minLabel}
        </p>
        <p className="earth-observatory__legend-zero" data-node-id="5:263">
          {activeLayer?.legend.midLabel ?? legendMeta.midLabel}
        </p>
        <p className="earth-observatory__legend-max" data-node-id="5:264">
          {activeLayer?.legend.maxLabel ?? legendMeta.maxLabel}
        </p>
      </div>

      <p className="earth-observatory__equator" data-node-id="5:265">
        0°
      </p>
      <p className="earth-observatory__attribution-left" data-node-id="5:266">
        © OpenFreeMap · NASA Earth Observations
      </p>
      <p className="earth-observatory__attribution-right" data-node-id="5:267">
        {rightAttribution}
      </p>
    </>
  )
}
