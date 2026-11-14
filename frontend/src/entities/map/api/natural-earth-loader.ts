import type { FeatureCollection, Geometry } from 'geojson'
import { GEOSPATIAL_PUBLIC_CONFIG } from '../../../shared/config/geospatial'
import type { CountryFeatureProperties } from '../../../widgets/world-map/model/types'

export interface NaturalEarthBundle {
  countries: FeatureCollection<Geometry, CountryFeatureProperties>
  coastlines: FeatureCollection<Geometry>
}

let cachedPromise: Promise<NaturalEarthBundle> | null = null

export function loadNaturalEarthBundle(): Promise<NaturalEarthBundle> {
  if (!cachedPromise) {
    cachedPromise = Promise.all([
      fetch(GEOSPATIAL_PUBLIC_CONFIG.naturalEarthCountriesUrl).then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to load countries GeoJSON (${res.status})`)
        }
        return res.json() as Promise<
          FeatureCollection<Geometry, CountryFeatureProperties>
        >
      }),
      fetch(GEOSPATIAL_PUBLIC_CONFIG.naturalEarthCoastlineUrl).then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to load coastline GeoJSON (${res.status})`)
        }
        return res.json() as Promise<FeatureCollection<Geometry>>
      }),
    ])
      .then(([countries, coastlines]) => ({ countries, coastlines }))
      .catch((err) => {
        cachedPromise = null
        throw err
      })
  }
  return cachedPromise
}
