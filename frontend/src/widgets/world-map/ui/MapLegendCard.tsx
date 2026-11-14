import { figmaAssets } from '../../../shared/config/assets'
import type {
  CountrySelectionSummary,
  VariableOption,
} from '../../../shared/store/ui-store'
import { ANOMALY_HOTSPOTS } from '../config/cartographic-data'
import { THEMATIC_LAYER_METADATA } from '../config/map-style'
import { formatCalloutReadout } from '../lib/use-region-interaction'

export interface MapLegendCardProps {
  selectedVariable: VariableOption
  selectedHotspotId: string
  selectedCountry: CountrySelectionSummary | null
  hoveredCountry: CountrySelectionSummary | null
  onClearSelectedCountry: () => void
}

export function MapLegendCard({
  selectedVariable,
  selectedHotspotId,
  selectedCountry,
  hoveredCountry,
  onClearSelectedCountry,
}: MapLegendCardProps) {
  const legendMeta = THEMATIC_LAYER_METADATA[selectedVariable]
  const activeHotspot =
    ANOMALY_HOTSPOTS.find((item) => item.id === selectedHotspotId) ??
    ANOMALY_HOTSPOTS[0]

  const activeCountry = hoveredCountry ?? selectedCountry
  const callout = formatCalloutReadout(
    selectedVariable,
    activeHotspot,
    activeCountry,
  )

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
          {legendMeta.shortTitle}
        </p>
        <p className="earth-observatory__legend-unit" data-node-id="5:260">
          {legendMeta.unit}
        </p>
        <div
          className="earth-observatory__legend-bar"
          data-node-id="5:261"
          style={{ background: legendMeta.gradientCss }}
          aria-hidden="true"
        />
        <p className="earth-observatory__legend-min" data-node-id="5:262">
          {legendMeta.minLabel}
        </p>
        <p className="earth-observatory__legend-zero" data-node-id="5:263">
          {legendMeta.midLabel}
        </p>
        <p className="earth-observatory__legend-max" data-node-id="5:264">
          {legendMeta.maxLabel}
        </p>
      </div>

      <p className="earth-observatory__equator" data-node-id="5:265">
        0°
      </p>
      <p className="earth-observatory__attribution-left" data-node-id="5:266">
        Natural Earth · NASA MODIS
      </p>
      <p className="earth-observatory__attribution-right" data-node-id="5:267">
        Illustrative spatial trends
      </p>
    </>
  )
}
