import type { MapLayerDefinition } from '../../../shared/types/geospatial'
import { formatCoordinatePair } from '../../../shared/lib/geojson-utils'
import { Crosshair } from '../../../shared/ui/explorer-icons'
import { usePointInspectionQuery } from '../api/use-map-provider-queries'
import { useExploreStore } from '../model/use-explore-store'

export function InspectorPointTab({ activeLayer }: { activeLayer: MapLayerDefinition }) {
  const primaryLayerId = useExploreStore((s) => s.primaryLayerId)
  const selectedDate = useExploreStore((s) => s.selectedDate)
  const inspectedPoint = useExploreStore((s) => s.inspectedPoint)
  const setInspectedPoint = useExploreStore((s) => s.setInspectedPoint)

  const pointQuery = usePointInspectionQuery(primaryLayerId, inspectedPoint, selectedDate)

  return (
    <div className="explorer-inspector-stack" role="tabpanel">
      {!inspectedPoint ? (
        <div className="explorer-empty-card">
          <Crosshair size={18} aria-hidden="true" />
          <h3>No pixel or coordinate inspected</h3>
          <p>
            Select the <strong>Inspect</strong> tool and click anywhere on the map to inspect WGS 84
            coordinates and source metadata for <strong>{activeLayer.shortName}</strong>.
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

          {pointQuery.isLoading ? (
            <p className="explorer-muted-copy">Querying provider metadata...</p>
          ) : pointQuery.data ? (
            <>
              <div className="explorer-status-banner is-unavailable">
                <strong>Observation data not connected</strong>
                <p>{pointQuery.data.message}</p>
              </div>

              <dl className="explorer-kv-list">
                <div>
                  <dt>Active layer</dt>
                  <dd>{activeLayer.name}</dd>
                </div>
                <div>
                  <dt>Product &amp; Version</dt>
                  <dd>
                    {pointQuery.data.productId} ({pointQuery.data.productVersion})
                  </dd>
                </div>
                <div>
                  <dt>Native resolution</dt>
                  <dd>{pointQuery.data.nativeSpatialResolution}</dd>
                </div>
                <div>
                  <dt>Requested date</dt>
                  <dd>{pointQuery.data.requestedDate}</dd>
                </div>
                <div>
                  <dt>Observation value</dt>
                  <dd>{pointQuery.data.formattedValue}</dd>
                </div>
                <div>
                  <dt>QA &amp; provenance</dt>
                  <dd>{pointQuery.data.quality.qaFlagSummary}</dd>
                </div>
              </dl>
              <p className="explorer-resolution-note">
                Coordinate clicks query only the native cell footprint (
                {pointQuery.data.nativeSpatialResolution}) and never interpolate finer resolution.
              </p>
            </>
          ) : null}
        </div>
      )}
    </div>
  )
}
