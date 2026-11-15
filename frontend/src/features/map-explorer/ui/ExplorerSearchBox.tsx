import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { Feature, Geometry } from 'geojson'
import { useLayerCatalogQuery } from '../../../shared/api/layers'
import { loadNaturalEarthBundle } from '../../../entities/map/api/natural-earth-loader'
import { countryPropertiesToSummary } from '../../../entities/map/model/map-renderer'
import { Search } from '../../../shared/ui/explorer-icons'
import type { CountryFeatureProperties } from '../../../widgets/world-map/model/types'
import { useExploreStore } from '../model/use-explore-store'

type CountryFeature = Feature<Geometry, CountryFeatureProperties>

interface SearchResultItem {
  id: string
  kind: 'coordinate' | 'country' | 'region' | 'layer'
  title: string
  subtitle: string
  center?: [number, number]
  zoom?: number
  countryFeature?: CountryFeature
  layerId?: string
}

const BIOME_BOOKMARKS: readonly {
  id: string
  name: string
  subtitle: string
  center: [number, number]
  zoom: number
}[] = [
  {
    id: 'region-amazon',
    name: 'Amazon Basin',
    subtitle: 'Tropical Moist Forest · Biomarker Benchmark',
    center: [-62.0, -5.5],
    zoom: 3.0,
  },
  {
    id: 'region-sahel',
    name: 'Sahel Belt',
    subtitle: 'Semi-Arid Transition · Precipitation Sensitivity',
    center: [11.5, 14.5],
    zoom: 3.1,
  },
  {
    id: 'region-siberia',
    name: 'Siberian Boreal',
    subtitle: 'Boreal Taiga · High-Latitude Warming Zone',
    center: [96.0, 61.5],
    zoom: 2.8,
  },
  {
    id: 'region-mediterranean',
    name: 'Mediterranean Basin',
    subtitle: 'Temperate Scrubland · Drought Recovery Study',
    center: [15.5, 38.0],
    zoom: 3.4,
  },
  {
    id: 'region-outback',
    name: 'Australian Outback',
    subtitle: 'Arid Interior · Thermal & Moisture Variability',
    center: [134.5, -24.5],
    zoom: 3.0,
  },
]

function parseCoordinateQuery(raw: string): [number, number] | null {
  const cleaned = raw.trim().replace(/[()]/g, '')
  const match = cleaned.match(/^(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)$/)
  if (!match) return null
  const first = Number(match[1])
  const second = Number(match[2])
  if (!Number.isFinite(first) || !Number.isFinite(second)) return null
  if (Math.abs(first) <= 90 && Math.abs(second) <= 180) return [second, first]
  if (Math.abs(first) <= 180 && Math.abs(second) <= 90) return [first, second]
  return null
}

export function ExplorerSearchBox({
  onFlyTo,
}: {
  onFlyTo: (center: [number, number], zoom?: number) => void
}) {
  const setSelectedCountry = useExploreStore((s) => s.setSelectedCountry)
  const setInspectedPoint = useExploreStore((s) => s.setInspectedPoint)
  const setPrimaryLayerId = useExploreStore((s) => s.setPrimaryLayerId)

  const [query, setQuery] = useState('')
  const [searchFocused, setSearchFocused] = useState(false)
  const [countries, setCountries] = useState<CountryFeature[]>([])
  const searchBoxRef = useRef<HTMLDivElement | null>(null)
  const catalogQuery = useLayerCatalogQuery()
  const layers = useMemo(() => catalogQuery.data ?? [], [catalogQuery.data])

  useEffect(() => {
    let active = true
    loadNaturalEarthBundle()
      .then((bundle) => {
        if (active) setCountries(bundle.countries.features)
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    const handleDocClick = (event: MouseEvent) => {
      if (searchBoxRef.current && event.target instanceof Node && !searchBoxRef.current.contains(event.target)) {
        setSearchFocused(false)
      }
    }
    document.addEventListener('mousedown', handleDocClick)
    return () => document.removeEventListener('mousedown', handleDocClick)
  }, [])

  const searchResults = useMemo<SearchResultItem[]>(() => {
    const q = query.trim().toLowerCase()
    if (!q) {
      return BIOME_BOOKMARKS.map((region) => ({
        id: region.id,
        kind: 'region',
        title: region.name,
        subtitle: region.subtitle,
        center: region.center,
        zoom: region.zoom,
      }))
    }

    const results: SearchResultItem[] = []
    const parsedCoord = parseCoordinateQuery(query)
    if (parsedCoord) {
      results.push({
        id: `coord-${parsedCoord[0]}-${parsedCoord[1]}`,
        kind: 'coordinate',
        title: `Jump to ${parsedCoord[1].toFixed(3)}°, ${parsedCoord[0].toFixed(3)}°`,
        subtitle: 'WGS 84 coordinate · EPSG:4326 inspect & center',
        center: parsedCoord,
        zoom: 4.2,
      })
    }

    for (const region of BIOME_BOOKMARKS) {
      if (region.name.toLowerCase().includes(q) || region.subtitle.toLowerCase().includes(q)) {
        results.push({
          id: region.id,
          kind: 'region',
          title: region.name,
          subtitle: region.subtitle,
          center: region.center,
          zoom: region.zoom,
        })
      }
    }

    let countryMatches = 0
    for (const feature of countries) {
      if (countryMatches >= 6) break
      const props = feature.properties
      if (
        props.name.toLowerCase().includes(q) ||
        props.nameLong.toLowerCase().includes(q) ||
        props.isoA3.toLowerCase().includes(q)
      ) {
        results.push({
          id: `country-${props.isoA3}`,
          kind: 'country',
          title: `${props.name} (${props.isoA3})`,
          subtitle: `${props.continent} · ${props.subregion}`,
          center: [props.labelLon, props.labelLat],
          zoom: 3.4,
          countryFeature: feature,
        })
        countryMatches++
      }
    }

    let layerMatches = 0
    for (const layer of layers) {
      if (layerMatches >= 4) break
      if (
        layer.name.toLowerCase().includes(q) ||
        layer.productId.toLowerCase().includes(q) ||
        layer.variable.toLowerCase().includes(q)
      ) {
        results.push({
          id: `layer-${layer.id}`,
          kind: 'layer',
          title: layer.name,
          subtitle: `${layer.dataSource} · ${layer.nativeSpatialResolution}`,
          layerId: layer.id,
        })
        layerMatches++
      }
    }

    return results
  }, [countries, layers, query])

  const selectResult = (item: SearchResultItem) => {
    if (item.kind === 'coordinate' && item.center) {
      onFlyTo(item.center, item.zoom ?? 4.2)
      setInspectedPoint({ lon: item.center[0], lat: item.center[1] })
    } else if (item.kind === 'country' && item.countryFeature) {
      setSelectedCountry(countryPropertiesToSummary(item.countryFeature.properties))
      if (item.center) onFlyTo(item.center, item.zoom ?? 3.4)
    } else if (item.kind === 'region' && item.center) {
      onFlyTo(item.center, item.zoom ?? 3.0)
    } else if (item.kind === 'layer' && item.layerId) {
      setPrimaryLayerId(item.layerId)
    }
    setSearchFocused(false)
  }

  const handleSearchSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (searchResults.length > 0) selectResult(searchResults[0])
  }

  return (
    <div className="explorer-search" ref={searchBoxRef}>
      <form className="explorer-search__form" onSubmit={handleSearchSubmit} role="search">
        <Search size={14} className="explorer-search__icon" aria-hidden="true" />
        <input
          type="search"
          className="explorer-search__input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setSearchFocused(true)}
          placeholder="Search country, biome, layer, or lat, lon"
          aria-label="Search country, biome, environmental layer, or lat lon coordinates"
        />
      </form>

      {searchFocused && (
        <div className="explorer-search__dropdown" role="listbox" aria-label="Search results">
          {searchResults.length === 0 ? (
            <div className="explorer-search__empty">
              No match. Try a country (e.g. Brazil), biome, MODIS/SMAP, or coordinates (-3.4, -62.2).
            </div>
          ) : (
            searchResults.map((item) => (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={false}
                className="explorer-search__option"
                onClick={() => selectResult(item)}
              >
                <span className="explorer-search__option-kind">{item.kind}</span>
                <span className="explorer-search__option-main">
                  <span className="explorer-search__option-title">{item.title}</span>
                  <span className="explorer-search__option-sub">{item.subtitle}</span>
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
