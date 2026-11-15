import type { Feature, FeatureCollection, LineString } from 'geojson'
import type { RegionOption } from '../../../shared/store/ui-store'
import type {
  CountryLabelAnchor,
  GeographicLabelAnchor,
  RegionCameraPreset,
} from '../model/types'

export const INITIAL_WORLD_CAMERA: RegionCameraPreset = {
  region: 'Global land',
  center: [10, 18],
  zoom: 0.62,
}

export const REGION_CAMERA_PRESETS: Record<RegionOption, RegionCameraPreset> = {
  'Global land': INITIAL_WORLD_CAMERA,
  'Amazon basin': {
    region: 'Amazon basin',
    center: [-62.0, -5.5],
    zoom: 2.75,
  },
  'Sahel belt': {
    region: 'Sahel belt',
    center: [11.5, 14.5],
    zoom: 2.75,
  },
  'Siberian boreal': {
    region: 'Siberian boreal',
    center: [96.0, 61.5],
    zoom: 2.35,
  },
  'Mediterranean basin': {
    region: 'Mediterranean basin',
    center: [15.5, 38.0],
    zoom: 3.1,
  },
  'Australian outback': {
    region: 'Australian outback',
    center: [134.5, -24.5],
    zoom: 2.85,
  },
}

export function buildGraticuleGeoJson(): FeatureCollection<
  LineString,
  { isEquator: boolean; label: string }
> {
  const features: Feature<LineString, { isEquator: boolean; label: string }>[] = []

  const meridians = [-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150]
  for (const lon of meridians) {
    const coords: [number, number][] = []
    for (let lat = -65; lat <= 78; lat += 3) {
      coords.push([lon, lat])
    }
    features.push({
      type: 'Feature',
      properties: {
        isEquator: false,
        label: `${Math.abs(lon)}°${lon < 0 ? 'W' : lon > 0 ? 'E' : ''}`,
      },
      geometry: {
        type: 'LineString',
        coordinates: coords,
      },
    })
  }

  const parallels = [-50, -30, -15, 0, 15, 30, 50, 68]
  for (const lat of parallels) {
    const coords: [number, number][] = []
    for (let lon = -179.5; lon <= 179.5; lon += 4) {
      coords.push([lon, lat])
    }
    features.push({
      type: 'Feature',
      properties: {
        isEquator: lat === 0,
        label: `${Math.abs(lat)}°${lat < 0 ? 'S' : lat > 0 ? 'N' : ''}`,
      },
      geometry: {
        type: 'LineString',
        coordinates: coords,
      },
    })
  }

  return {
    type: 'FeatureCollection',
    features,
  }
}

export const CONTINENT_AND_OCEAN_LABELS: readonly GeographicLabelAnchor[] = [
  {
    id: 'north-america',
    text: 'NORTH AMERICA',
    longitude: -102,
    latitude: 42,
    kind: 'continent',
    nodeId: '5:209',
  },
  {
    id: 'south-america',
    text: 'SOUTH AMERICA',
    longitude: -60,
    latitude: -21,
    kind: 'continent',
    nodeId: '5:210',
  },
  {
    id: 'europe',
    text: 'EUROPE',
    longitude: 15,
    latitude: 50,
    kind: 'continent',
    nodeId: '5:211',
  },
  {
    id: 'africa',
    text: 'AFRICA',
    longitude: 19,
    latitude: 5,
    kind: 'continent',
    nodeId: '5:212',
  },
  {
    id: 'asia',
    text: 'ASIA',
    longitude: 88,
    latitude: 44,
    kind: 'continent',
    nodeId: '5:213',
  },
  {
    id: 'australia',
    text: 'AUSTRALIA',
    longitude: 134,
    latitude: -26,
    kind: 'continent',
    nodeId: '5:214',
  },
  {
    id: 'pacific-ocean',
    text: 'PACIFIC OCEAN',
    longitude: -135,
    latitude: -8,
    kind: 'ocean',
    nodeId: '5:215',
  },
  {
    id: 'atlantic-ocean',
    text: 'ATLANTIC OCEAN',
    longitude: -33,
    latitude: 12,
    kind: 'ocean',
    nodeId: '5:216',
  },
  {
    id: 'indian-ocean',
    text: 'INDIAN OCEAN',
    longitude: 78,
    latitude: -24,
    kind: 'ocean',
    nodeId: '5:217',
  },
]

export const MAJOR_COUNTRY_LABELS: readonly CountryLabelAnchor[] = [
  { isoA3: 'CAN', name: 'Canada', longitude: -106.3, latitude: 58.2, labelRank: 1, terraRegion: 'Siberian boreal' },
  { isoA3: 'USA', name: 'United States', longitude: -98.5, latitude: 38.8, labelRank: 1, terraRegion: 'Global land' },
  { isoA3: 'MEX', name: 'Mexico', longitude: -102.5, latitude: 23.6, labelRank: 2, terraRegion: 'Global land' },
  { isoA3: 'BRA', name: 'Brazil', longitude: -52.8, latitude: -10.8, labelRank: 1, terraRegion: 'Amazon basin' },
  { isoA3: 'ARG', name: 'Argentina', longitude: -64.2, latitude: -35.4, labelRank: 2, terraRegion: 'Global land' },
  { isoA3: 'PER', name: 'Peru', longitude: -75.2, latitude: -9.4, labelRank: 2, terraRegion: 'Amazon basin' },
  { isoA3: 'COL', name: 'Colombia', longitude: -73.2, latitude: 4.1, labelRank: 2, terraRegion: 'Amazon basin' },
  { isoA3: 'BOL', name: 'Bolivia', longitude: -64.7, latitude: -16.7, labelRank: 3, terraRegion: 'Amazon basin' },
  { isoA3: 'VEN', name: 'Venezuela', longitude: -66.2, latitude: 7.1, labelRank: 3, terraRegion: 'Amazon basin' },
  { isoA3: 'RUS', name: 'Russia', longitude: 96.0, latitude: 61.8, labelRank: 1, terraRegion: 'Siberian boreal' },
  { isoA3: 'CHN', name: 'China', longitude: 103.8, latitude: 35.6, labelRank: 1, terraRegion: 'Global land' },
  { isoA3: 'IND', name: 'India', longitude: 78.9, latitude: 22.4, labelRank: 1, terraRegion: 'Global land' },
  { isoA3: 'KAZ', name: 'Kazakhstan', longitude: 67.2, latitude: 48.0, labelRank: 2, terraRegion: 'Siberian boreal' },
  { isoA3: 'MNG', name: 'Mongolia', longitude: 103.8, latitude: 46.8, labelRank: 3, terraRegion: 'Siberian boreal' },
  { isoA3: 'IDN', name: 'Indonesia', longitude: 117.5, latitude: -2.2, labelRank: 2, terraRegion: 'Global land' },
  { isoA3: 'AUS', name: 'Australia', longitude: 134.4, latitude: -25.0, labelRank: 1, terraRegion: 'Australian outback' },
  { isoA3: 'DZA', name: 'Algeria', longitude: 2.6, latitude: 28.1, labelRank: 2, terraRegion: 'Mediterranean basin' },
  { isoA3: 'MLI', name: 'Mali', longitude: -3.5, latitude: 17.3, labelRank: 2, terraRegion: 'Sahel belt' },
  { isoA3: 'NER', name: 'Niger', longitude: 9.4, latitude: 17.4, labelRank: 2, terraRegion: 'Sahel belt' },
  { isoA3: 'TCD', name: 'Chad', longitude: 18.6, latitude: 15.4, labelRank: 2, terraRegion: 'Sahel belt' },
  { isoA3: 'SDN', name: 'Sudan', longitude: 30.2, latitude: 15.6, labelRank: 2, terraRegion: 'Sahel belt' },
  { isoA3: 'NGA', name: 'Nigeria', longitude: 8.2, latitude: 9.6, labelRank: 2, terraRegion: 'Sahel belt' },
  { isoA3: 'ETH', name: 'Ethiopia', longitude: 39.6, latitude: 8.6, labelRank: 2, terraRegion: 'Sahel belt' },
  { isoA3: 'COD', name: 'DR Congo', longitude: 23.6, latitude: -2.8, labelRank: 2, terraRegion: 'Global land' },
  { isoA3: 'ZAF', name: 'South Africa', longitude: 24.5, latitude: -29.0, labelRank: 2, terraRegion: 'Global land' },
  { isoA3: 'EGY', name: 'Egypt', longitude: 29.8, latitude: 26.5, labelRank: 2, terraRegion: 'Mediterranean basin' },
  { isoA3: 'SAU', name: 'Saudi Arabia', longitude: 44.5, latitude: 24.0, labelRank: 2, terraRegion: 'Global land' },
  { isoA3: 'TUR', name: 'Turkey', longitude: 35.2, latitude: 39.0, labelRank: 2, terraRegion: 'Mediterranean basin' },
  { isoA3: 'UKR', name: 'Ukraine', longitude: 31.4, latitude: 49.0, labelRank: 2, terraRegion: 'Global land' },
  { isoA3: 'ESP', name: 'Spain', longitude: -3.7, latitude: 40.2, labelRank: 2, terraRegion: 'Mediterranean basin' },
  { isoA3: 'FRA', name: 'France', longitude: 2.4, latitude: 46.6, labelRank: 2, terraRegion: 'Mediterranean basin' },
  { isoA3: 'ITA', name: 'Italy', longitude: 12.6, latitude: 42.8, labelRank: 3, terraRegion: 'Mediterranean basin' },
  { isoA3: 'GRC', name: 'Greece', longitude: 22.0, latitude: 39.2, labelRank: 3, terraRegion: 'Mediterranean basin' },
  { isoA3: 'MAR', name: 'Morocco', longitude: -6.5, latitude: 32.0, labelRank: 3, terraRegion: 'Mediterranean basin' },
  { isoA3: 'NOR', name: 'Norway', longitude: 9.5, latitude: 62.0, labelRank: 3, terraRegion: 'Siberian boreal' },
  { isoA3: 'SWE', name: 'Sweden', longitude: 15.5, latitude: 62.5, labelRank: 3, terraRegion: 'Siberian boreal' },
  { isoA3: 'FIN', name: 'Finland', longitude: 26.0, latitude: 64.0, labelRank: 3, terraRegion: 'Siberian boreal' },
]

