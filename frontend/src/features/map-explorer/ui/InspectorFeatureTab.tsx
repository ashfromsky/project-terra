import { loadNaturalEarthBundle } from '../../../entities/map/api/natural-earth-loader'
import type { AoiFeature, AoiRole } from '../../../shared/types/geospatial'
import { MapPin } from '../../../shared/ui/explorer-icons'
import { useExploreStore } from '../model/use-explore-store'

export function InspectorFeatureTab() {
  const selectedCountry = useExploreStore((s) => s.selectedCountry)
  const addCountryAsAoi = useExploreStore((s) => s.addCountryAsAoi)
  const setTab = useExploreStore((s) => s.setInspectorTab)

  const handleAssignCountryAoi = async (role: AoiRole) => {
    if (!selectedCountry) return
    const bundle = await loadNaturalEarthBundle()
    const match = bundle.countries.features.find((f) => f.properties.isoA3 === selectedCountry.isoA3)
    if (!match) return
    addCountryAsAoi(selectedCountry, match.geometry as AoiFeature['geometry'], role)
    setTab('aoi')
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

          <div className="explorer-action-stack">
            <button
              type="button"
              className="explorer-action-btn explorer-action-btn--region-a"
              onClick={() => handleAssignCountryAoi('regionA')}
            >
              Assign as Region A
            </button>
            <button
              type="button"
              className="explorer-action-btn explorer-action-btn--region-b"
              onClick={() => handleAssignCountryAoi('regionB')}
            >
              Assign as Region B
            </button>
            <button
              type="button"
              className="explorer-action-btn"
              onClick={() => handleAssignCountryAoi('primary')}
            >
              Add as Primary AOI
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
