import { useQuery } from '@tanstack/react-query'
import { inspectLayerPoint, resolveLayerEffectiveDate } from '../../../shared/api/layers'
import { formatCoordinatePair } from '../../../shared/lib/geojson-utils'
import type { MapLayerDefinition } from '../../../shared/types/geospatial'
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

  const isConnected = activeLayer?.availabilityStatus === 'connected'
  const effectiveDate = resolveLayerEffectiveDate(activeLayer, selectedDate)

  const pointQuery = useQuery({
    queryKey: [
      'layers',
      'point',
      activeLayer?.id ?? null,
      inspectedPoint?.lon ?? null,
      inspectedPoint?.lat ?? null,
      effectiveDate ?? null,
    ],
    queryFn: () =>
      inspectLayerPoint(activeLayer!.id, {
        lon: inspectedPoint!.lon,
        lat: inspectedPoint!.lat,
        timestamp: effectiveDate,
      }),
    enabled: Boolean(inspectedPoint && activeLayer && isConnected),
    staleTime: 15_000,
    retry: 1,
  })

  const pointData = pointQuery.data ?? null

  return (
    <div className="explorer-inspector-stack" role="tabpanel">
      {!inspectedPoint ? (
        <div className="explorer-empty-card">
          <Crosshair size={18} aria-hidden="true" />
          <h3>No pixel or coordinate inspected</h3>
          <p>
            Select the <strong>Inspect</strong> tool and click anywhere on the map to sample the
            nearest native pixel and provenance metadata for{' '}
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

          {!activeLayer ? (
            <div className="explorer-status-banner is-unavailable">
              <strong>{catalogLoading ? 'Loading layer catalog…' : 'Layer catalog unavailable'}</strong>
              <p>Connect to TERRA Core API to inspect raster pixels.</p>
            </div>
          ) : !isConnected ? (
            <div className="explorer-status-banner is-unavailable">
              <strong>Layer unavailable</strong>
              <p>
                {activeLayer.unavailableReason ??
                  `${activeLayer.productId}.${activeLayer.productVersion} has no ingested COG raster available for point sampling.`}
              </p>
            </div>
          ) : pointQuery.isPending ? (
            <div className="explorer-status-banner" role="status">
              <strong>Sampling native raster pixel…</strong>
              <p>Querying backend COG at native {activeLayer.nativeSpatialResolution} resolution.</p>
            </div>
          ) : pointQuery.isError ? (
            <div className="explorer-status-banner is-error" role="alert">
              <strong>Point inspection failed</strong>
              <p>{pointQuery.error instanceof Error ? pointQuery.error.message : String(pointQuery.error)}</p>
              <button
                type="button"
                className="explorer-inline-reset"
                onClick={() => void pointQuery.refetch()}
              >
                Retry
              </button>
            </div>
          ) : pointData?.status === 'ok' ? (
            <div className="explorer-status-banner is-connected">
              <strong>
                {pointData.value !== null && pointData.value !== undefined
                  ? `${pointData.value.toFixed(4)} ${pointData.unit ?? activeLayer.unit}`
                  : `Value unavailable (${pointData.unit ?? activeLayer.unit})`}
              </strong>
              <p>
                Nearest-neighbor native pixel sampled at {pointData.timestamp ?? effectiveDate ?? 'latest'}
                {pointData.qaPassed === false ? ' · QA flagged' : pointData.qaPassed === true ? ' · QA passed' : ''}
              </p>
            </div>
          ) : (
            <div className="explorer-status-banner is-unavailable">
              <strong>
                {pointData?.status === 'outside_bounds'
                  ? 'Outside dataset bounds'
                  : pointData?.status === 'nodata'
                    ? 'NoData / masked pixel'
                    : 'Point observation unavailable'}
              </strong>
              <p>
                {pointData?.reason ??
                  'No valid observation is recorded at this coordinate for the selected date.'}
              </p>
            </div>
          )}

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
                  <dd>
                    {pointData?.nominalResolutionM
                      ? `${pointData.nominalResolutionM} m (${activeLayer.nativeSpatialResolution})`
                      : activeLayer.nativeSpatialResolution}
                  </dd>
                </div>
                <div>
                  <dt>Effective date</dt>
                  <dd>{pointData?.timestamp ?? effectiveDate ?? selectedDate}</dd>
                </div>
                <div>
                  <dt>Observation value</dt>
                  <dd>
                    {pointData?.status === 'ok' && pointData.value !== null && pointData.value !== undefined
                      ? `${pointData.value.toFixed(4)} ${pointData.unit ?? activeLayer.unit}${
                          pointData.rawValue !== null && pointData.rawValue !== undefined
                            ? ` (raw ${pointData.rawValue})`
                            : ''
                        }`
                      : pointData?.status ?? (isConnected ? 'Pending' : 'Unavailable')}
                  </dd>
                </div>
                {pointData?.crs && (
                  <div>
                    <dt>Grid CRS &amp; pixel</dt>
                    <dd>
                      {pointData.crs}
                      {pointData.pixelRow !== null &&
                      pointData.pixelRow !== undefined &&
                      pointData.pixelCol !== null &&
                      pointData.pixelCol !== undefined
                        ? ` · row ${pointData.pixelRow}, col ${pointData.pixelCol}`
                        : ''}
                    </dd>
                  </div>
                )}
                {pointData?.datasetId && (
                  <div>
                    <dt>Dataset ID</dt>
                    <dd>{pointData.datasetId}</dd>
                  </div>
                )}
                <div>
                  <dt>QA &amp; provenance</dt>
                  <dd>
                    {pointData?.qaValue !== null && pointData?.qaValue !== undefined
                      ? `QA=${pointData.qaValue} (${pointData.qaPassed ? 'pass' : 'screened'}) · `
                      : ''}
                    {activeLayer.qaPolicy}
                  </dd>
                </div>
              </dl>

              {pointData?.timeSeries && pointData.timeSeries.length > 0 && (
                <div className="explorer-control-block">
                  <div className="explorer-control-row">
                    <span className="explorer-control-label">
                      Pixel time series ({pointData.timeSeries.length} obs)
                    </span>
                  </div>
                  <dl className="explorer-kv-list">
                    {pointData.timeSeries.map((pt) => (
                      <div key={pt.timestamp}>
                        <dt>{pt.timestamp}</dt>
                        <dd>
                          {pt.value !== null && pt.value !== undefined
                            ? `${pt.value.toFixed(4)} ${pointData.unit ?? activeLayer.unit}`
                            : 'NoData'}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}

              <p className="explorer-resolution-note">
                Coordinate clicks sample nearest-neighbor pixels in WGS 84 / native grid without
                sub-pixel interpolation beyond {activeLayer.nativeSpatialResolution}.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
