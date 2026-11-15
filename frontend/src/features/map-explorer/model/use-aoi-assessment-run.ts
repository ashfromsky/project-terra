import { useState } from 'react'
import { createAssessment } from '../../../shared/api/assessments'
import { ApiError } from '../../../shared/api/client'
import type {
  AssessmentDetailResponse,
  AutoProvisionResponse,
} from '../../../shared/api/contracts'
import { autoProvisionDatasets } from '../../../shared/api/data-sources'

export type AoiAssessmentPhase = 'idle' | 'provisioning' | 'submitting' | 'queued' | 'error'

export interface AoiAssessmentRunInput {
  regionId: string
  aoiName: string
  analysisStart: string
  analysisEnd: string
  includeVegetation: boolean
  includeSoilMoisture: boolean
}

export interface AoiAssessmentRunResult {
  provision: AutoProvisionResponse
  assessment: AssessmentDetailResponse
}

export const MIN_BASELINE_YEARS = 2

function toErrorMessage(cause: unknown): string {
  if (cause instanceof ApiError) return cause.message
  if (cause instanceof Error && cause.message.trim().length > 0) return cause.message
  return 'Assessment submission failed for an unknown reason.'
}

/**
 * Drives the map AOI -> real GHS observations -> Scientific Core workflow.
 *
 * Provisioning runs first so the assessment receives the dataset IDs that GHS actually
 * produced from real provider observations. The assessment itself is queued for
 * terra-worker instead of executed inside this request.
 */
export function useAoiAssessmentRun() {
  const [phase, setPhase] = useState<AoiAssessmentPhase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [provision, setProvision] = useState<AutoProvisionResponse | null>(null)
  const [assessment, setAssessment] = useState<AssessmentDetailResponse | null>(null)

  const reset = () => {
    setPhase('idle')
    setError(null)
    setProvision(null)
    setAssessment(null)
  }

  const run = async (
    input: AoiAssessmentRunInput,
  ): Promise<AoiAssessmentRunResult | null> => {
    const { regionId, analysisStart, analysisEnd } = input

    if (!regionId) {
      setPhase('error')
      setError('Save this AOI to TERRA Core before running a scientific assessment.')
      return null
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(analysisStart) || !/^\d{4}-\d{2}-\d{2}$/.test(analysisEnd)) {
      setPhase('error')
      setError('Choose a valid analysis start and end date.')
      return null
    }
    if (analysisStart > analysisEnd) {
      setPhase('error')
      setError('Analysis start date must be on or before the analysis end date.')
      return null
    }

    setPhase('provisioning')
    setError(null)
    setProvision(null)
    setAssessment(null)

    const analysisStartIso = `${analysisStart}T00:00:00Z`
    const analysisEndIso = `${analysisEnd}T23:59:59Z`
    const desiredDomains = [
      'climate',
      ...(input.includeVegetation ? ['vegetation'] : []),
      ...(input.includeSoilMoisture ? ['soil_moisture'] : []),
    ]

    try {
      const provisionResult = await autoProvisionDatasets({
        regionId,
        bbox: null,
        analysisStart: analysisStartIso,
        analysisEnd: analysisEndIso,
        targetCadence: 'monthly',
        baselineType: 'out_of_sample',
        referenceStart: null,
        referenceEnd: null,
        minReferenceYears: MIN_BASELINE_YEARS,
        qaLevel: 'permissive',
        existingDatasetIds: [],
        desiredDomains,
        maxGranulesPerProduct: 48,
      })
      setProvision(provisionResult)

      const datasetIds = provisionResult.datasetIds ?? []
      if (datasetIds.length === 0) {
        const details = (provisionResult.steps ?? [])
          .map((step) => `${step.domain}: ${step.detail}`)
          .filter((detail) => detail.trim().length > 0)
          .join(' ')
        throw new ApiError(
          422,
          details.length > 0
            ? `No real observations were provisioned for this AOI and period. ${details}`
            : 'No real observations were provisioned for this AOI and period.',
        )
      }

      setPhase('submitting')
      const created = await createAssessment({
        title: `Map AOI Assessment · ${input.aoiName.trim() || regionId} · ${analysisStart} → ${analysisEnd}`,
        regionId,
        executeNow: false,
        ghsDatasetIds: datasetIds,
        inlineDatasets: [],
        requestConfig: {
          request_id: `map-aoi-${Date.now()}`,
          analysis_profile: 'quick',
          analysis_start: analysisStartIso,
          analysis_end: analysisEndIso,
          target_cadence: 'monthly',
          qa_level: 'permissive',
          // Derived raster publication is a map-overlay concern, not part of the
          // scientific result. Skipping it keeps the worker response time bounded.
          publish_derived_spatial_artifacts: false,
          baseline: {
            baseline_type: 'out_of_sample',
            exclude_assessment_overlap: true,
            allow_explicit_full_period: false,
            min_years_required: MIN_BASELINE_YEARS,
            min_samples_per_bin: MIN_BASELINE_YEARS,
          },
        },
      })

      setAssessment(created)
      setPhase('queued')
      return { provision: provisionResult, assessment: created }
    } catch (cause) {
      setPhase('error')
      setError(toErrorMessage(cause))
      return null
    }
  }

  return { phase, error, provision, assessment, run, reset }
}
