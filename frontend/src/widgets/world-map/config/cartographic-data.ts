import type { Feature, FeatureCollection, LineString, Polygon } from 'geojson'
import type { RegionOption } from '../../../shared/store/ui-store'
import type {
  AnomalyHotspotDatum,
  CountryLabelAnchor,
  GeographicLabelAnchor,
  RegionAoiFeatureProperties,
  RegionCameraPreset,
  SyntheticAnomalyCellDatum,
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

export const ANOMALY_HOTSPOTS: readonly AnomalyHotspotDatum[] = [
  {
    id: 'amazon',
    title: 'Amazon basin',
    regionName: 'Amazon basin',
    coordinates: [-62.5, -5.2],
    lstTrendLabel: '+0.31°C / decade',
    ndviLabel: '0.78 NDVI (−0.018 / dec)',
    eviLabel: '0.58 EVI (−0.014 / dec)',
    precipLabel: '−18.4 mm / mo anomaly',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'teal',
    radiusMeters: 620000,
    isSyntheticDemo: true,
  },
  {
    id: 'north-america',
    title: 'Western North America',
    regionName: 'Global land',
    coordinates: [-98.0, 41.0],
    lstTrendLabel: '+0.34°C / decade',
    ndviLabel: '0.46 NDVI (−0.011 / dec)',
    eviLabel: '0.35 EVI (−0.009 / dec)',
    precipLabel: '−14.2 mm / mo anomaly',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'coral',
    radiusMeters: 560000,
    isSyntheticDemo: true,
  },
  {
    id: 'sahel',
    title: 'Sahel belt',
    regionName: 'Sahel belt',
    coordinates: [14.0, 14.2],
    lstTrendLabel: '+0.38°C / decade',
    ndviLabel: '0.24 NDVI (+0.009 / dec)',
    eviLabel: '0.18 EVI (+0.006 / dec)',
    precipLabel: '−24.2 mm / mo anomaly',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'coral',
    radiusMeters: 580000,
    isSyntheticDemo: true,
  },
  {
    id: 'siberia',
    title: 'Siberian boreal',
    regionName: 'Siberian boreal',
    coordinates: [94.0, 61.5],
    lstTrendLabel: '+0.46°C / decade',
    ndviLabel: '0.56 NDVI (+0.024 / dec)',
    eviLabel: '0.43 EVI (+0.019 / dec)',
    precipLabel: '+12.8 mm / mo anomaly',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'coral',
    radiusMeters: 660000,
    isSyntheticDemo: true,
  },
  {
    id: 'se-asia',
    title: 'Maritime Southeast Asia',
    regionName: 'Global land',
    coordinates: [108.0, 12.5],
    lstTrendLabel: '+0.14°C / decade',
    ndviLabel: '0.74 NDVI (+0.008 / dec)',
    eviLabel: '0.56 EVI (+0.007 / dec)',
    precipLabel: '+16.5 mm / mo anomaly',
    significanceLabel: 'p = 0.012 · Significant',
    tone: 'teal',
    radiusMeters: 540000,
    isSyntheticDemo: true,
  },
  {
    id: 'australia',
    title: 'Australian outback',
    regionName: 'Australian outback',
    coordinates: [134.5, -24.5],
    lstTrendLabel: '+0.29°C / decade',
    ndviLabel: '0.28 NDVI (−0.015 / dec)',
    eviLabel: '0.21 EVI (−0.012 / dec)',
    precipLabel: '−19.8 mm / mo anomaly',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'coral',
    radiusMeters: 580000,
    isSyntheticDemo: true,
  },
  {
    id: 'mediterranean',
    title: 'Mediterranean basin',
    regionName: 'Mediterranean basin',
    coordinates: [15.5, 38.2],
    lstTrendLabel: '+0.36°C / decade',
    ndviLabel: '0.41 NDVI (−0.016 / dec)',
    eviLabel: '0.31 EVI (−0.012 / dec)',
    precipLabel: '−15.6 mm / mo anomaly',
    significanceLabel: 'p < 0.001 · Significant',
    tone: 'coral',
    radiusMeters: 500000,
    isSyntheticDemo: true,
  },
]

export const REGION_AOI_GEOJSON: FeatureCollection<Polygon, RegionAoiFeatureProperties> = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: {
        id: 'aoi-amazon',
        regionName: 'Amazon basin',
        title: 'Amazon basin AOI',
        subtitle: 'Illustrative watershed boundary · Synthetic demo',
        strokeColor: [21, 155, 145, 240],
        fillColor: [21, 155, 145, 38],
        isSyntheticDemo: true,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [-76.5, 2.5],
            [-69.0, 4.8],
            [-59.5, 3.8],
            [-50.2, -0.8],
            [-48.5, -6.5],
            [-53.8, -13.5],
            [-62.4, -15.2],
            [-71.2, -12.6],
            [-76.8, -5.4],
            [-76.5, 2.5],
          ],
        ],
      },
    },
    {
      type: 'Feature',
      properties: {
        id: 'aoi-sahel',
        regionName: 'Sahel belt',
        title: 'Sahel belt AOI',
        subtitle: 'Semi-arid transition zone · Synthetic demo',
        strokeColor: [199, 127, 109, 235],
        fillColor: [199, 127, 109, 34],
        isSyntheticDemo: true,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [-16.5, 17.8],
            [2.0, 18.5],
            [22.0, 17.8],
            [36.5, 15.8],
            [36.0, 10.6],
            [18.0, 10.8],
            [-2.0, 11.5],
            [-16.5, 12.6],
            [-16.5, 17.8],
          ],
        ],
      },
    },
    {
      type: 'Feature',
      properties: {
        id: 'aoi-siberia',
        regionName: 'Siberian boreal',
        title: 'Siberian boreal AOI',
        subtitle: 'High-latitude taiga zone · Synthetic demo',
        strokeColor: [199, 127, 109, 235],
        fillColor: [199, 127, 109, 34],
        isSyntheticDemo: true,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [64.0, 67.5],
            [95.0, 69.0],
            [128.0, 66.5],
            [132.0, 55.5],
            [102.0, 53.0],
            [70.0, 55.0],
            [64.0, 67.5],
          ],
        ],
      },
    },
    {
      type: 'Feature',
      properties: {
        id: 'aoi-mediterranean',
        regionName: 'Mediterranean basin',
        title: 'Mediterranean basin AOI',
        subtitle: 'Circum-Mediterranean biome · Synthetic demo',
        strokeColor: [49, 147, 206, 235],
        fillColor: [49, 147, 206, 32],
        isSyntheticDemo: true,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [-8.5, 43.8],
            [12.0, 45.2],
            [35.5, 41.5],
            [36.0, 31.0],
            [10.0, 31.5],
            [-8.0, 33.5],
            [-8.5, 43.8],
          ],
        ],
      },
    },
    {
      type: 'Feature',
      properties: {
        id: 'aoi-australia',
        regionName: 'Australian outback',
        title: 'Australian outback AOI',
        subtitle: 'Arid interior basin · Synthetic demo',
        strokeColor: [199, 127, 109, 235],
        fillColor: [199, 127, 109, 34],
        isSyntheticDemo: true,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [118.5, -18.5],
            [141.5, -18.5],
            [144.0, -30.5],
            [121.0, -31.0],
            [118.5, -18.5],
          ],
        ],
      },
    },
  ],
}

function generateBiomeGridCells(): SyntheticAnomalyCellDatum[] {
  const cells: SyntheticAnomalyCellDatum[] = []
  const seeds: Array<{
    regionName: RegionOption
    lonStart: number
    lonEnd: number
    latStart: number
    latEnd: number
    step: number
    baseLst: number
    baseNdvi: number
    basePrecip: number
  }> = [
    {
      regionName: 'Amazon basin',
      lonStart: -72,
      lonEnd: -52,
      latStart: -12,
      latEnd: 2,
      step: 4,
      baseLst: 0.31,
      baseNdvi: 0.78,
      basePrecip: -18.4,
    },
    {
      regionName: 'Sahel belt',
      lonStart: -12,
      lonEnd: 32,
      latStart: 11,
      latEnd: 17,
      step: 4,
      baseLst: 0.38,
      baseNdvi: 0.24,
      basePrecip: -24.2,
    },
    {
      regionName: 'Siberian boreal',
      lonStart: 70,
      lonEnd: 122,
      latStart: 56,
      latEnd: 66,
      step: 5,
      baseLst: 0.46,
      baseNdvi: 0.56,
      basePrecip: 12.8,
    },
    {
      regionName: 'Mediterranean basin',
      lonStart: -6,
      lonEnd: 32,
      latStart: 34,
      latEnd: 43,
      step: 4.5,
      baseLst: 0.36,
      baseNdvi: 0.41,
      basePrecip: -15.6,
    },
    {
      regionName: 'Australian outback',
      lonStart: 121,
      lonEnd: 141,
      latStart: -29,
      latEnd: -19,
      step: 4,
      baseLst: 0.29,
      baseNdvi: 0.28,
      basePrecip: -19.8,
    },
  ]

  let index = 1
  for (const seed of seeds) {
    for (let lon = seed.lonStart; lon < seed.lonEnd; lon += seed.step) {
      for (let lat = seed.latStart; lat < seed.latEnd; lat += seed.step) {
        const wave = Math.sin(lon * 0.14) * Math.cos(lat * 0.18)
        const lstDelta = Number((seed.baseLst + wave * 0.11).toFixed(2))
        const ndviScore = Number(
          Math.max(0.08, Math.min(0.88, seed.baseNdvi + wave * 0.09)).toFixed(2),
        )
        const eviScore = Number((ndviScore * 0.78).toFixed(2))
        const precipDelta = Number((seed.basePrecip + wave * 9.5).toFixed(1))

        cells.push({
          id: `cell-${index++}`,
          regionName: seed.regionName,
          polygon: [
            [lon, lat],
            [lon + seed.step * 0.88, lat],
            [lon + seed.step * 0.88, lat + seed.step * 0.88],
            [lon, lat + seed.step * 0.88],
            [lon, lat],
          ],
          lstDelta,
          ndviScore,
          eviScore,
          precipDelta,
          isSyntheticDemo: true,
        })
      }
    }
  }

  return cells
}

export const SYNTHETIC_ANOMALY_CELLS: readonly SyntheticAnomalyCellDatum[] =
  generateBiomeGridCells()
