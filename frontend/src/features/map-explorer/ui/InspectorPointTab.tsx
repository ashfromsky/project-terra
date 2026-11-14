import type { MapLayerDefinition } from '../../../shared/types/geospatial'
import { formatCoordinatePair } from '../../../shared/lib/geojson-utils'
import { Crosshair } from '../../../shared/ui/explorer-icons'
import { useExploreStore } from '../model/use-explore-store'

interface InspectorPointTabProps {
  activeLayer: MapLayerDefinition | null
  catalogLoading: boolean
}

export function InspectorPointTab({ activeLayer, catalogLoading }: InspectorPointTabProps) {
  const selectedDate = useExploreStore((s) => s.selectedDate)
  const inspectedPoint = useExploreStore((s) => s.inspectedPoint)
  const setInspectedPoint = useExploreStore((s) => s.setInspectedPoint)

  return (
    <div className="explorer-inspector-stack" role="tabpanel">
      {!inspectedPoint ? (
        <div className="explorer-empty-card">
          <Crosshair size={18} aria-hidden="true" />
          <h3>No pixel or coordinate inspected</h3>
          <p>
            Select the <strong>Inspect</strong> tool and click anywhere on the map to inspect WGS 84
            coordinates and source metadata for{' '}
            <strong>{activeLayer ? activeLayer.shortName : 'selected layer'}</strong>.
          </p>
        </div>
      ) : (
        <div className="explorer-inspector-card">
          <div className="explorer-inspector-card__head">
            <div>
              <span className="explorer-overline">Inspected Coordinate</span>
              <h3>{formatCoordinatePair(inspectedPoint.lon, inspectedPoint.lat)}</h3>
            </div>
            <button
              type="button"
              className="explorer-inline-reset"
              onClick={() => setInspectedPoint(null)}
            >
              Clear
            </button>
          </div>

          <div className="explorer-status-banner is-unavailable">
            <strong>Observation data not connected</strong>
            <p>
              {activeLayer
                ? `Actual ${activeLayer.productId}.${activeLayer.productVersion} pixel observations at native ${activeLayer.nativeSpatialResolution} resolution await backend COG / Zarr sampling.`
                : catalogLoading
                  ? 'Loading active layer metadata from TERRA Core API…'
                  : 'Layer catalog is not connected. Point values are not interpolated in the browser.'}
            </p>
          </div>

          {activeLayer && (
            <>
              <dl className="explorer-kv-list">
                <div>
                  <dt>Active layer</dt>
                  <dd>{activeLayer.name}</dd>
                </div>
                <div>
                  <dt>Product &amp; Version</dt>
                  <dd>
                    {activeLayer.productId} ({activeLayer.productVersion})
                  </dd>
                </div>
                <div>
                  <dt>Native resolution</dt>
                  <dd>{activeLayer.nativeSpatialResolution}</dd>
                </div>
                <div>
                  <dt>Requested date</dt>
                  <dd>{selectedDate}</dd>
                </div>
                <div>
                  <dt>Observation value</dt>
                  <dd>Not connected ({activeLayer.unit})</dd>
                </div>
                <div>
                  <dt>QA &amp; provenance</dt>
                  <dd>{activeLayer.qaPolicy}</dd>
                </div>
              </dl>
              <p className="explorer-resolution-note">
                Coordinate clicks record exact WGS 84 (EPSG:4326) position and never interpolate finer
                than native {activeLayer.nativeSpatialResolution} cell resolution.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
