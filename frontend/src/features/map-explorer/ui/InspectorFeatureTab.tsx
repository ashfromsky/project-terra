import { loadNaturalEarthBundle } from '../../../entities/map/api/natural-earth-loader'
import { normalizeAoiGeometry } from '../../../shared/lib/geojson-utils'
import type { AoiRole } from '../../../shared/types/geospatial'
import { MapPin } from '../../../shared/ui/explorer-icons'
import { useAoiWorkspace } from '../model/use-aoi-workspace'
import { useExploreStore } from '../model/use-explore-store'

export function InspectorFeatureTab() {
  const selectedCountry = useExploreStore((s) => s.selectedCountry)
  const { assignCountryAsAoi, syncPending, syncError } = useAoiWorkspace()

  const handleAssignCountryAoi = async (role: AoiRole) => {
    if (!selectedCountry || syncPending) return
    const bundle = await loadNaturalEarthBundle()
    const match = bundle.countries.features.find((f) => f.properties.isoA3 === selectedCountry.isoA3)
    const normalized = match ? normalizeAoiGeometry(match.geometry) : null
    if (!normalized) return
    await assignCountryAsAoi(selectedCountry, normalized, role)
  }

  return (
    <div className="explorer-inspector-stack" role="tabpanel">
      {!selectedCountry ? (
        <div className="explorer-empty-card">
          <MapPin size={18} aria-hidden="true" />
          <h3>No boundary feature selected</h3>
          <p>
            Click a country polygon in Equal Earth, Globe, or Mercator mode to view metadata and
            promote it to Region A or Region B for comparison.
          </p>
        </div>
      ) : (
        <div className="explorer-inspector-card">
          <span className="explorer-overline">Natural Earth 1:110m Feature</span>
          <h3>
            {selectedCountry.name} ({selectedCountry.isoA3})
          </h3>
          <dl className="explorer-kv-list">
            <div>
              <dt>Classification</dt>
              <dd>
                {selectedCountry.continent} · {selectedCountry.terraRegion}
              </dd>
            </div>
            <div>
              <dt>Subregion</dt>
              <dd>{selectedCountry.subregion}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>Country observation time series pending backend connection</dd>
            </div>
          </dl>

          <div className="explorer-notice-box explorer-notice-box--compact">
            <span>
              Any preview fill values shown on-screen are SYNTHETIC / DEMONSTRATION DATA and not
              official country statistics.
            </span>
          </div>

          {syncError && (
            <div className="explorer-status-banner is-error" role="alert">
              <strong>Could not save region</strong>
              <p>{syncError}</p>
            </div>
          )}

          <div className="explorer-action-stack">
            <button
              type="button"
              disabled={syncPending}
              className="explorer-action-btn explorer-action-btn--region-a"
              onClick={() => void handleAssignCountryAoi('regionA')}
            >
              {syncPending ? 'Saving…' : 'Assign as Region A'}
            </button>
            <button
              type="button"
              disabled={syncPending}
              className="explorer-action-btn explorer-action-btn--region-b"
              onClick={() => void handleAssignCountryAoi('regionB')}
            >
              {syncPending ? 'Saving…' : 'Assign as Region B'}
            </button>
            <button
              type="button"
              disabled={syncPending}
              className="explorer-action-btn"
              onClick={() => void handleAssignCountryAoi('primary')}
            >
              {syncPending ? 'Saving…' : 'Add as Primary AOI'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
