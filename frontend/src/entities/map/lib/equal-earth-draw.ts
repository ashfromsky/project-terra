import { geoArea, geoEqualEarth, geoGraticule10, type geoPath, type GeoPermissibleObjects } from 'd3-geo'
import type { Feature, Geometry, LineString } from 'geojson'
import type { BASEMAP_PROVIDER_REGISTRY } from '../../../shared/config/geospatial'
import { createRectangleGeometry } from '../../../shared/lib/geojson-utils'
import type { AoiGeometry, BasemapId } from '../../../shared/types/geospatial'
import {
  CONTINENT_AND_OCEAN_LABELS,
  MAJOR_COUNTRY_LABELS,
  REGION_AOI_GEOJSON,
} from '../../../widgets/world-map/config/cartographic-data'
import type { CountryFeatureProperties } from '../../../widgets/world-map/model/types'
import { extractPreviewFeatureValue, interpolateColorFromLayer } from '../../layer/lib/layer-coloring'
import type { NaturalEarthBundle } from '../api/natural-earth-loader'
import type { MapRenderState } from '../model/map-renderer'
import type { CachedGibsRaster } from './gibs-overview-loader'

export const EQUAL_EARTH_SPHERE: GeoPermissibleObjects = { type: 'Sphere' }

const EQUATOR_GEOJSON: Feature<LineString> = {
  type: 'Feature',
  properties: {},
  geometry: {
    type: 'LineString',
    coordinates: [[-180, 0], [-90, 0], [0, 0], [90, 0], [180, 0]],
  },
}

function normalizeGeometryForD3(geometry: AoiGeometry): AoiGeometry {
  const feature: Feature<AoiGeometry> = { type: 'Feature', properties: {}, geometry }
  if (geoArea(feature) <= 2 * Math.PI) return geometry
  if (geometry.type === 'Polygon') {
    return { type: 'Polygon', coordinates: geometry.coordinates.map((ring) => [...ring].reverse()) }
  }
  return {
    type: 'MultiPolygon',
    coordinates: geometry.coordinates.map((poly) => poly.map((ring) => [...ring].reverse())),
  }
}

export function drawEqualEarthCanvas(params: {
  canvas: HTMLCanvasElement
  width: number
  height: number
  projection: ReturnType<typeof geoEqualEarth>
  pathGen: ReturnType<typeof geoPath>
  basemap: (typeof BASEMAP_PROVIDER_REGISTRY)[BasemapId]
  raster: CachedGibsRaster | null | undefined
  step: number
}): void {
  const { canvas, width, height, projection, pathGen, basemap, raster, step } = params
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const targetW = Math.round(width * dpr)
  const targetH = Math.round(height * dpr)
  if (canvas.width !== targetW || canvas.height !== targetH) {
    canvas.width = targetW
    canvas.height = targetH
  }
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  ctx.save()
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, width, height)
  ctx.fillStyle = '#f0f5f6'
  ctx.fillRect(0, 0, width, height)

  const spherePath = new Path2D(pathGen(EQUAL_EARTH_SPHERE) ?? '')
  ctx.save()
  ctx.clip(spherePath)
  ctx.fillStyle = basemap.backgroundOceanColor
  ctx.fillRect(0, 0, width, height)

  if (raster) {
    const imgWidth = Math.ceil(width / step)
    const imgHeight = Math.ceil(height / step)
    const offscreen = document.createElement('canvas')
    offscreen.width = imgWidth
    offscreen.height = imgHeight
    const offCtx = offscreen.getContext('2d')
    if (offCtx) {
      const out = offCtx.createImageData(imgWidth, imgHeight)
      const degPerPx = 0.28125
      for (let py = 0; py < imgHeight; py++) {
        const sy = py * step + step * 0.5
        for (let px = 0; px < imgWidth; px++) {
          const sx = px * step + step * 0.5
          const coords = projection.invert?.([sx, sy])
          if (!coords) continue
          const [lon, lat] = coords
          if (lon < -180 || lon > 180 || lat < -90 || lat > 90) continue
          const rx = Math.max(0, Math.min(raster.width - 1, Math.floor((lon + 180) / degPerPx)))
          const ry = Math.max(0, Math.min(raster.height - 1, Math.floor((90 - lat) / degPerPx)))
          const srcIdx = (ry * raster.width + rx) * 4
          const dstIdx = (py * imgWidth + px) * 4
          out.data[dstIdx] = raster.data[srcIdx]
          out.data[dstIdx + 1] = raster.data[srcIdx + 1]
          out.data[dstIdx + 2] = raster.data[srcIdx + 2]
          out.data[dstIdx + 3] = 255
        }
      }
      offCtx.putImageData(out, 0, 0)
      ctx.imageSmoothingEnabled = true
      ctx.drawImage(offscreen, 0, 0, width, height)
    }
  }

  ctx.restore()
  ctx.restore()
}

export function drawEqualEarthSvgVectors(params: {
  svg: SVGSVGElement
  state: MapRenderState
  bundle: NaturalEarthBundle | null
  width: number
  height: number
  projection: ReturnType<typeof geoEqualEarth>
  pathGen: ReturnType<typeof geoPath>
  basemap: (typeof BASEMAP_PROVIDER_REGISTRY)[BasemapId]
  hasRasterBasemap: boolean
}): void {
  const { svg, state, bundle, width, height, projection, pathGen, basemap, hasRasterBasemap } = params
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`)

  const showPreviewChoropleth = Boolean(
    state.activeLayer &&
      state.activeLayer.visible &&
      state.syntheticPreviewEnabled &&
      state.activeLayer.layer.isSyntheticPreview,
  )
  const fragments: string[] = []

  if (state.showGraticules) {
    const gratD = pathGen(geoGraticule10()) ?? ''
    const eqD = pathGen(EQUATOR_GEOJSON) ?? ''
    const gratColor = hasRasterBasemap ? 'rgba(255,255,255,0.22)' : '#dbe6e9'
    const eqColor = hasRasterBasemap ? 'rgba(255,255,255,0.45)' : '#bfd2d7'
    fragments.push(`<path d="${gratD}" fill="none" stroke="${gratColor}" stroke-width="0.8" />`)
    fragments.push(`<path d="${eqD}" fill="none" stroke="${eqColor}" stroke-width="1.15" stroke-dasharray="4 3" />`)
  }

  if (bundle) {
    const countriesPaths: string[] = []
    for (const feature of bundle.countries.features) {
      const d = pathGen(feature as GeoPermissibleObjects)
      if (!d) continue
      const props = feature.properties as CountryFeatureProperties
      const iso = props.isoA3
      const isSelected = state.selectedCountry?.isoA3 === iso
      const isHovered = state.hoveredCountryIso === iso

      let fill = hasRasterBasemap ? 'transparent' : basemap.landFallbackColor
      let fillOpacity = hasRasterBasemap ? 0 : 1

      if (showPreviewChoropleth && state.activeLayer) {
        const val = extractPreviewFeatureValue(props, state.activeLayer.layer)
        fill = interpolateColorFromLayer(
          state.activeLayer.layer,
          val,
          state.activeLayer.minValue,
          state.activeLayer.maxValue,
        )
        fillOpacity = state.activeLayer.opacity
      }

      countriesPaths.push(
        `<path data-iso="${iso}" d="${d}" fill="${fill}" fill-opacity="${fillOpacity}" stroke="${
          state.showBorders ? basemap.borderColor : 'none'
        }" stroke-width="${state.showBorders ? 0.75 : 0}" style="cursor:pointer" />`,
      )

      if (isHovered && !isSelected) {
        countriesPaths.push(
          `<path d="${d}" fill="rgba(21,155,145,0.22)" stroke="#159b91" stroke-width="1.5" pointer-events="none" />`,
        )
      }
      if (isSelected) {
        countriesPaths.push(
          `<path d="${d}" fill="rgba(21,155,145,0.28)" stroke="#0e4d4a" stroke-width="2" pointer-events="none" />`,
        )
      }
    }
    fragments.push(`<g class="equal-earth-countries">${countriesPaths.join('')}</g>`)

    if (state.showBorders) {
      const coastD = pathGen(bundle.coastlines as GeoPermissibleObjects) ?? ''
      fragments.push(`<path d="${coastD}" fill="none" stroke="${basemap.borderColor}" stroke-width="0.9" pointer-events="none" />`)
    }
  }

  if (state.showRegionBoundaries) {
    for (const regionFeature of REGION_AOI_GEOJSON.features) {
      const d = pathGen(regionFeature as GeoPermissibleObjects)
      if (d) {
        fragments.push(
          `<path d="${d}" fill="rgba(21,155,145,0.08)" stroke="#159b91" stroke-width="1.2" stroke-dasharray="4 3" pointer-events="none" />`,
        )
      }
    }
  }

  for (const aoi of state.aois) {
    const normalizedGeom = normalizeGeometryForD3(aoi.geometry)
    const d = pathGen({ type: 'Feature', properties: {}, geometry: normalizedGeom } as GeoPermissibleObjects)
    if (!d) continue
    const isRegionB = aoi.properties.role === 'regionB'
    const isSelected = aoi.properties.id === state.selectedAoiId
    const stroke = isRegionB ? '#3193ce' : '#159b91'
    const fill = isRegionB
      ? isSelected ? 'rgba(49,147,206,0.28)' : 'rgba(49,147,206,0.16)'
      : isSelected ? 'rgba(21,155,145,0.28)' : 'rgba(21,155,145,0.16)'
    fragments.push(`<path d="${d}" fill="${fill}" stroke="${stroke}" stroke-width="${isSelected ? 2.4 : 1.7}" pointer-events="none" />`)
  }

  if (state.draftVertices.length > 0) {
    if (state.interactionMode === 'draw-rectangle' && state.draftHoverPoint) {
      const rectGeom = createRectangleGeometry(state.draftVertices[0], state.draftHoverPoint)
      const d = pathGen({ type: 'Feature', properties: {}, geometry: normalizeGeometryForD3(rectGeom) } as GeoPermissibleObjects)
      if (d) {
        fragments.push(`<path d="${d}" fill="rgba(21,155,145,0.18)" stroke="#159b91" stroke-width="1.8" stroke-dasharray="5 3" pointer-events="none" />`)
      }
    } else {
      const coords = state.draftHoverPoint ? [...state.draftVertices, state.draftHoverPoint] : [...state.draftVertices]
      const line: Feature<Geometry> = { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } }
      const d = pathGen(line as GeoPermissibleObjects)
      if (d) {
        fragments.push(`<path d="${d}" fill="none" stroke="#159b91" stroke-width="2" stroke-dasharray="4 3" pointer-events="none" />`)
      }
      for (const vertex of state.draftVertices) {
        const projected = projection(vertex)
        if (projected) {
          fragments.push(`<circle cx="${projected[0]}" cy="${projected[1]}" r="4" fill="#ffffff" stroke="#159b91" stroke-width="2" pointer-events="none" />`)
        }
      }
    }
  }

  if (state.inspectedPoint) {
    const pt = projection([state.inspectedPoint.lon, state.inspectedPoint.lat])
    if (pt) {
      fragments.push(
        `<g pointer-events="none"><circle cx="${pt[0]}" cy="${pt[1]}" r="11" fill="rgba(21,155,145,0.18)" stroke="#159b91" stroke-width="1.5" /><circle cx="${pt[0]}" cy="${pt[1]}" r="3.5" fill="#159b91" stroke="#ffffff" stroke-width="1.5" /></g>`,
      )
    }
  }

  const sphereD = pathGen(EQUAL_EARTH_SPHERE) ?? ''
  fragments.push(
    `<path d="${sphereD}" fill="none" stroke="${hasRasterBasemap ? 'rgba(255,255,255,0.35)' : '#c8d6dc'}" stroke-width="1.15" pointer-events="none" />`,
  )
  svg.innerHTML = fragments.join('')
}

export function drawEqualEarthOverlayLabels(params: {
  container: HTMLDivElement
  state: MapRenderState
  width: number
  height: number
  scaleFactor: number
  projection: ReturnType<typeof geoEqualEarth>
  hasRasterBasemap: boolean
}): void {
  const { container, state, width, height, scaleFactor, projection, hasRasterBasemap } = params
  if (!state.showLabels) {
    container.innerHTML = ''
    return
  }

  const labelColor = hasRasterBasemap ? 'rgba(245,250,252,0.88)' : '#365058'
  const geoColor = hasRasterBasemap ? 'rgba(220,235,242,0.75)' : '#7f939c'
  const elements: string[] = []

  if (scaleFactor <= 3.2) {
    for (const item of CONTINENT_AND_OCEAN_LABELS) {
      const pt = projection([item.longitude, item.latitude])
      if (!pt || pt[0] < 24 || pt[0] > width - 24 || pt[1] < 16 || pt[1] > height - 16) continue
      elements.push(
        `<span style="position:absolute;left:${Math.round(pt[0])}px;top:${Math.round(pt[1])}px;transform:translate(-50%,-50%);font-size:9px;font-weight:500;letter-spacing:0.75px;color:${geoColor};white-space:nowrap;text-shadow:${
          hasRasterBasemap ? '0 1px 2px rgba(0,0,0,0.65)' : '0 1px 2px rgba(255,255,255,0.9)'
        }">${item.text}</span>`,
      )
    }
  }

  const maxRank = scaleFactor >= 2.6 ? 3 : scaleFactor >= 1.5 ? 2 : 1
  for (const country of MAJOR_COUNTRY_LABELS) {
    const isSelected = state.selectedCountry?.isoA3 === country.isoA3
    const isHovered = state.hoveredCountryIso === country.isoA3
    if (country.isoA3 === 'AUS' && scaleFactor < 1.35 && !isSelected && !isHovered) continue
    if (country.labelRank > maxRank && !isSelected && !isHovered) continue
    const pt = projection([country.longitude, country.latitude])
    if (!pt || pt[0] < 24 || pt[0] > width - 24 || pt[1] < 16 || pt[1] > height - 16) continue
    const bg = isSelected
      ? 'rgba(231,244,242,0.96)'
      : hasRasterBasemap ? 'rgba(13,28,39,0.55)' : 'rgba(255,255,255,0.68)'
    const color = isSelected ? '#0e4d4a' : labelColor
    elements.push(
      `<span style="position:absolute;left:${Math.round(pt[0])}px;top:${Math.round(pt[1])}px;transform:translate(-50%,-50%);font-size:8.5px;font-weight:${
        isSelected || isHovered ? 600 : 500
      };color:${color};background:${bg};padding:1px 4px;border-radius:3px;white-space:nowrap">${country.name}</span>`,
    )
  }

  container.innerHTML = elements.join('')
}
