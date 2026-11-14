import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router'
import { LAYER_BY_ID } from '../../../entities/layer/model/layer-catalog'
import { BASEMAP_PROVIDER_REGISTRY, PROJECTION_REGISTRY } from '../../../shared/config/geospatial'
import type { BasemapId, ProjectionId } from '../../../shared/types/geospatial'
import { useExploreStore } from '../model/use-explore-store'

export function useExploreUrlSync() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initializedRef = useRef(false)

  const projection = useExploreStore((s) => s.projection)
  const basemap = useExploreStore((s) => s.basemap)
  const primaryLayerId = useExploreStore((s) => s.primaryLayerId)
  const selectedDate = useExploreStore((s) => s.selectedDate)
  const comparisonMode = useExploreStore((s) => s.comparisonMode)

  const setProjection = useExploreStore((s) => s.setProjection)
  const setBasemap = useExploreStore((s) => s.setBasemap)
  const setPrimaryLayerId = useExploreStore((s) => s.setPrimaryLayerId)
  const setSelectedDate = useExploreStore((s) => s.setSelectedDate)
  const setComparisonMode = useExploreStore((s) => s.setComparisonMode)

  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true

    const urlProj = searchParams.get('proj') as ProjectionId | null
    if (urlProj && urlProj in PROJECTION_REGISTRY) {
      setProjection(urlProj)
    }

    const urlBasemap = searchParams.get('basemap') as BasemapId | null
    if (urlBasemap && urlBasemap in BASEMAP_PROVIDER_REGISTRY) {
      setBasemap(urlBasemap)
    }

    const urlLayer = searchParams.get('layer')
    if (urlLayer && urlLayer in LAYER_BY_ID) {
      setPrimaryLayerId(urlLayer)
    }

    const urlDate = searchParams.get('date')
    if (urlDate && /^\d{4}-\d{2}-\d{2}$/.test(urlDate)) {
      setSelectedDate(urlDate)
    }

    const urlCmp = searchParams.get('cmp')
    if (urlCmp === '1') {
      setComparisonMode(true)
    }
  }, [
    searchParams,
    setBasemap,
    setComparisonMode,
    setPrimaryLayerId,
    setProjection,
    setSelectedDate,
  ])

  useEffect(() => {
    if (!initializedRef.current) return
    const next = new URLSearchParams(searchParams)
    next.set('proj', projection)
    next.set('basemap', basemap)
    next.set('layer', primaryLayerId)
    next.set('date', selectedDate)
    if (comparisonMode) {
      next.set('cmp', '1')
    } else {
      next.delete('cmp')
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true })
    }
  }, [
    basemap,
    comparisonMode,
    primaryLayerId,
    projection,
    searchParams,
    selectedDate,
    setSearchParams,
  ])
}
