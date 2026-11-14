import { useCallback, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useCurrentUserQuery } from '../../../shared/api/auth'
import {
  createRegion,
  deleteRegion,
  REGIONS_QUERY_KEY,
  regionResponseToAoiFeature,
  toRegionGeometryInput,
  updateRegionMetadata,
  useRegionsQuery,
} from '../../../shared/api/regions'
import type { RegionCreateRequest } from '../../../shared/api/contracts'
import type { CountrySelectionSummary } from '../../../shared/store/ui-store'
import type { AoiFeature, AoiGeometry, AoiRole } from '../../../shared/types/geospatial'
import { buildDraftCompletionAoi } from './explore-aoi-helpers'
import { useExploreStore } from './use-explore-store'

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim().length > 0 ? error.message : fallback
}

export function useAoiWorkspace() {
  const queryClient = useQueryClient()
  const currentUserQuery = useCurrentUserQuery()
  const currentUser = currentUserQuery.data ?? null
  const isAuthenticated = Boolean(currentUser)
  const regionsQuery = useRegionsQuery(isAuthenticated)

  const localAois = useExploreStore((s) => s.aois)
  const selectedAoiId = useExploreStore((s) => s.selectedAoiId)
  const setSelectedAoiId = useExploreStore((s) => s.setSelectedAoiId)
  const aoiSyncError = useExploreStore((s) => s.aoiSyncError)
  const setAoiSyncError = useExploreStore((s) => s.setAoiSyncError)
  const aoiSyncPending = useExploreStore((s) => s.aoiSyncPending)
  const setAoiSyncPending = useExploreStore((s) => s.setAoiSyncPending)
  const cancelDraftAoi = useExploreStore((s) => s.cancelDraftAoi)
  const addLocalCountryAoi = useExploreStore((s) => s.addCountryAsAoi)
  const updateLocalAoiRole = useExploreStore((s) => s.updateAoiRole)
  const renameLocalAoi = useExploreStore((s) => s.renameAoi)
  const removeLocalAoi = useExploreStore((s) => s.removeAoi)
  const clearLocalAois = useExploreStore((s) => s.clearAois)
  const setRightInspectorOpen = useExploreStore((s) => s.setRightInspectorOpen)
  const setInspectorTab = useExploreStore((s) => s.setInspectorTab)

  const persistedAois = useMemo<AoiFeature[]>(
    () => (regionsQuery.data ?? []).map(regionResponseToAoiFeature),
    [regionsQuery.data],
  )

  const aois = isAuthenticated ? persistedAois : localAois

  const selectedAoi = useMemo(
    () => aois.find((item) => item.properties.id === selectedAoiId) ?? aois[0] ?? null,
    [aois, selectedAoiId],
  )

  const demoteConflictingRole = useCallback(
    async (role: AoiRole, exceptId?: string) => {
      if (role !== 'regionA' && role !== 'regionB') return
      const existing = persistedAois.filter(
        (item) => item.properties.role === role && item.properties.id !== exceptId,
      )
      await Promise.all(
        existing.map((item) => updateRegionMetadata(item.properties.id, { role: 'primary' })),
      )
    },
    [persistedAois],
  )

  const createPersistedRegion = useCallback(
    async (payload: RegionCreateRequest, role: AoiRole): Promise<AoiFeature | null> => {
      setAoiSyncError(null)
      setAoiSyncPending(true)
      try {
        await demoteConflictingRole(role)
        const created = await createRegion(payload)
        await queryClient.invalidateQueries({ queryKey: REGIONS_QUERY_KEY })
        setSelectedAoiId(created.id)
        setRightInspectorOpen(true)
        setInspectorTab('aoi')
        return regionResponseToAoiFeature(created)
      } catch (error) {
        setAoiSyncError(getErrorMessage(error, 'Failed to save region to backend'))
        setRightInspectorOpen(true)
        setInspectorTab('aoi')
        return null
      } finally {
        setAoiSyncPending(false)
      }
    },
    [
      demoteConflictingRole,
      queryClient,
      setAoiSyncError,
      setAoiSyncPending,
      setInspectorTab,
      setRightInspectorOpen,
      setSelectedAoiId,
    ],
  )

  const completeDraftAoi = useCallback(
    async (lon?: number, lat?: number) => {
      const store = useExploreStore.getState()
      const candidate = buildDraftCompletionAoi({
        interactionMode: store.interactionMode,
        draftVertices: store.draftVertices,
        activeAoiRole: store.activeAoiRole,
        lon,
        lat,
      })
      if (!candidate) return

      if (!isAuthenticated) {
        store.completeDraftAoi(lon, lat)
        return
      }

      cancelDraftAoi()
      const labelPrefix =
        candidate.properties.role === 'regionA'
          ? 'Region A'
          : candidate.properties.role === 'regionB'
            ? 'Region B'
            : 'AOI'
      await createPersistedRegion(
        {
          name: `${labelPrefix} · ${persistedAois.length + 1}`,
          role: candidate.properties.role,
          shapeType: candidate.properties.shapeType,
          geometry: toRegionGeometryInput(candidate.geometry),
        },
        candidate.properties.role,
      )
    },
    [cancelDraftAoi, createPersistedRegion, isAuthenticated, persistedAois.length],
  )

  const assignCountryAsAoi = useCallback(
    async (
      country: CountrySelectionSummary,
      geometry: AoiGeometry,
      roleOverride?: AoiRole,
    ) => {
      const role = roleOverride ?? useExploreStore.getState().activeAoiRole
      if (!isAuthenticated) {
        addLocalCountryAoi(country, geometry, role)
        setInspectorTab('aoi')
        return
      }
      await createPersistedRegion(
        {
          name: country.name,
          role,
          shapeType: 'feature',
          isoA3: country.isoA3,
          geometry: toRegionGeometryInput(geometry),
        },
        role,
      )
    },
    [addLocalCountryAoi, createPersistedRegion, isAuthenticated, setInspectorTab],
  )

  const updateAoiRole = useCallback(
    async (aoiId: string, role: AoiRole) => {
      if (!isAuthenticated) {
        updateLocalAoiRole(aoiId, role)
        return
      }
      setAoiSyncError(null)
      setAoiSyncPending(true)
      try {
        await demoteConflictingRole(role, aoiId)
        await updateRegionMetadata(aoiId, { role })
        await queryClient.invalidateQueries({ queryKey: REGIONS_QUERY_KEY })
      } catch (error) {
        setAoiSyncError(getErrorMessage(error, 'Failed to update region role'))
      } finally {
        setAoiSyncPending(false)
      }
    },
    [
      demoteConflictingRole,
      isAuthenticated,
      queryClient,
      setAoiSyncError,
      setAoiSyncPending,
      updateLocalAoiRole,
    ],
  )

  const renameAoi = useCallback(
    async (aoiId: string, name: string) => {
      const cleaned = name.trim()
      if (!cleaned) return
      if (!isAuthenticated) {
        renameLocalAoi(aoiId, cleaned)
        return
      }
      setAoiSyncError(null)
      setAoiSyncPending(true)
      try {
        await updateRegionMetadata(aoiId, { name: cleaned })
        await queryClient.invalidateQueries({ queryKey: REGIONS_QUERY_KEY })
      } catch (error) {
        setAoiSyncError(getErrorMessage(error, 'Failed to rename region'))
      } finally {
        setAoiSyncPending(false)
      }
    },
    [isAuthenticated, queryClient, renameLocalAoi, setAoiSyncError, setAoiSyncPending],
  )

  const removeAoi = useCallback(
    async (aoiId: string) => {
      if (!isAuthenticated) {
        removeLocalAoi(aoiId)
        return
      }
      setAoiSyncError(null)
      setAoiSyncPending(true)
      try {
        await deleteRegion(aoiId)
        if (useExploreStore.getState().selectedAoiId === aoiId) {
          setSelectedAoiId(null)
        }
        await queryClient.invalidateQueries({ queryKey: REGIONS_QUERY_KEY })
      } catch (error) {
        setAoiSyncError(getErrorMessage(error, 'Failed to delete region'))
      } finally {
        setAoiSyncPending(false)
      }
    },
    [isAuthenticated, queryClient, removeLocalAoi, setAoiSyncError, setAoiSyncPending, setSelectedAoiId],
  )

  const clearAois = useCallback(async () => {
    if (!isAuthenticated) {
      clearLocalAois()
      return
    }
    setAoiSyncError(null)
    setAoiSyncPending(true)
    try {
      await Promise.all(persistedAois.map((item) => deleteRegion(item.properties.id)))
      setSelectedAoiId(null)
      await queryClient.invalidateQueries({ queryKey: REGIONS_QUERY_KEY })
    } catch (error) {
      setAoiSyncError(getErrorMessage(error, 'Failed to clear saved regions'))
    } finally {
      setAoiSyncPending(false)
    }
  }, [
    clearLocalAois,
    isAuthenticated,
    persistedAois,
    queryClient,
    setAoiSyncError,
    setAoiSyncPending,
    setSelectedAoiId,
  ])

  return {
    aois,
    selectedAoi,
    setSelectedAoiId,
    isAuthenticated,
    isLoadingRegions: isAuthenticated && regionsQuery.isLoading,
    regionsError: isAuthenticated && regionsQuery.isError ? regionsQuery.error : null,
    refetchRegions: regionsQuery.refetch,
    syncPending: aoiSyncPending,
    syncError: aoiSyncError,
    clearSyncError: () => setAoiSyncError(null),
    completeDraftAoi,
    assignCountryAsAoi,
    updateAoiRole,
    renameAoi,
    removeAoi,
    clearAois,
  }
}
