import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchClient, ApiError, unwrapApiResponse } from './client'
import type {
  AssessmentComparisonResponse,
  AssessmentDetailResponse,
  AssessmentSummaryResponse,
  CompareAssessmentsRequest,
  CreateAssessmentRequest,
  MethodCatalogItemResponse,
} from './contracts'

export type {
  AssessmentComparisonResponse,
  AssessmentDetailResponse,
  AssessmentSummaryResponse,
  CompareAssessmentsRequest,
  CreateAssessmentRequest,
  MethodCatalogItemResponse,
}

export const ASSESSMENT_METHODS_QUERY_KEY = ['assessments', 'methods'] as const
export const ASSESSMENTS_LIST_QUERY_KEY = ['assessments', 'list'] as const

export function assessmentDetailQueryKey(assessmentId: string) {
  return ['assessments', 'detail', assessmentId] as const
}

export interface ParsedStageReport {
  stageName: string
  priority: string
  status: string
  durationMs: number
  skipReason: string | null
  warnings: string[]
  errors: string[]
}

export interface ParsedQualityReport {
  datasetId: string
  variableName: string
  totalSteps: number
  validSteps: number
  missingSteps: number
  validFraction: number
  missingFraction: number
  qaScreenedOutCount: number
  outOfRangeCount: number
  warnings: string[]
}

export interface ParsedTrendSummary {
  datasetId: string
  variableName: string
  variant: string
  sampleCount: number
  validCount: number
  direction: string
  pValue: number | null
  sensSlope: number | null
  slopeUnit: string
  warnings: string[]
}

export interface ParsedEventResistanceDetail {
  eventStart: string
  eventEnd: string | null
  peakNegativeZscore: number
  resistance: number
}

export interface ParsedResilienceDimension {
  dimension: string
  available: boolean
  status: string
  value: number | null
  unit: string
  formula: string
  interpretation: string
  assumptions: string[]
  limitations: string[]
  eventValues: ParsedEventResistanceDetail[]
}

export interface ParsedResilienceSummary {
  datasetId: string
  variableName: string
  resistance: ParsedResilienceDimension | null
  recovery: ParsedResilienceDimension | null
  stability: ParsedResilienceDimension | null
  sensitivity: ParsedResilienceDimension | null
  compositeTriStatus: string
  compositeTriReason: string
}

export interface ParsedRecoveryEvent {
  datasetId: string
  variableName: string
  eventStart: string
  eventPeakTimestamp: string
  observationEnd: string
  deficitMagnitude: number
  timeToRecoveryDays: number | null
  recoveryCompleteness: number
  elapsedRecoveryRate: number | null
  rateUnit: string
  status: string
  seasonalCaveat: string
  warnings: string[]
}

export interface ParsedUncertaintySummary {
  dataQualityConfidence: string
  dataQualityRationale: string
  statisticalConfidence: string
  statisticalRationale: string
  scientificConfidence: string
  scientificRationale: string
  methodologicalLimitations: string[]
}

export interface ParsedProvenanceRecord {
  inputDigestSha256: string
  configDigestSha256: string
  generatedAtUtc: string
  datasetLineage: Record<string, unknown>[]
  methodsInvoked: {
    methodId: string
    version: string
    name: string
  }[]
  packageVersions: Record<string, string>
}

export interface ParsedTemporalSeries {
  datasetId: string
  variableName: string
  units: string
  cadence: string
  aggregationOperator: string
  timestamps: string[]
  values: (number | null)[]
  coverageFractions: (number | null)[]
  interpolatedIndices: number[]
  warnings: string[]
}

export interface ParsedBaselineClimatology {
  datasetId: string
  variableName: string
  units: string
  baselineType: string
  binMeans: (number | null)[]
  binStds: (number | null)[]
  binCounts: number[]
  warnings: string[]
}

export interface ParsedPersistentRun {
  startTimestamp: string
  endTimestamp: string
  durationSteps: number
  peakZscore: number
  severity: string
}

export interface ParsedAnomalySeries {
  datasetId: string
  variableName: string
  units: string
  timestamps: string[]
  rawAnomalies: (number | null)[]
  standardZscores: (number | null)[]
  robustZscores: (number | null)[]
  persistentRuns: ParsedPersistentRun[]
  warnings: string[]
}

export interface ParsedCrossVariableResult {
  xVariable: string
  yVariable: string
  pearsonR: number | null
  spearmanRho: number | null
  lagSteps: number
  pValue: number | null
  sampleCount: number
  caveat: string
  warnings: string[]
}

export interface ParsedScientificResult {
  assessmentId: string
  status: string
  stages: ParsedStageReport[]
  qualityReports: ParsedQualityReport[]
  temporalSeries: ParsedTemporalSeries[]
  baselines: ParsedBaselineClimatology[]
  anomalies: ParsedAnomalySeries[]
  trends: ParsedTrendSummary[]
  recoveries: ParsedRecoveryEvent[]
  crossVariable: ParsedCrossVariableResult[]
  resilience: ParsedResilienceSummary[]
  uncertainty: ParsedUncertaintySummary | null
  provenance: ParsedProvenanceRecord | null
  warnings: string[]
  errors: string[]
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  return value as Record<string, unknown>
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function asOptionalString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function asStringList(value: unknown): string[] {
  return asArray(value).filter((item): item is string => typeof item === 'string')
}

function parseResilienceDimension(raw: unknown): ParsedResilienceDimension | null {
  const rec = asRecord(raw)
  if (!rec) return null
  const eventValues = asArray(rec.event_values ?? rec.eventValues)
    .map((item): ParsedEventResistanceDetail | null => {
      const ev = asRecord(item)
      if (!ev) return null
      const peakZ = asNumber(ev.peak_negative_zscore ?? ev.peakNegativeZscore)
      const resistance = asNumber(ev.resistance)
      if (peakZ === null || resistance === null) return null
      return {
        eventStart: asString(ev.event_start ?? ev.eventStart),
        eventEnd: asOptionalString(ev.event_end ?? ev.eventEnd),
        peakNegativeZscore: peakZ,
        resistance,
      }
    })
    .filter((item): item is ParsedEventResistanceDetail => item !== null)

  return {
    dimension: asString(rec.dimension),
    available: asBoolean(rec.available),
    status: asString(rec.status, 'unavailable'),
    value: asNumber(rec.value),
    unit: asString(rec.unit),
    formula: asString(rec.formula),
    interpretation: asString(rec.interpretation),
    assumptions: asStringList(rec.assumptions),
    limitations: asStringList(rec.limitations),
    eventValues,
  }
}

export function parseScientificAssessmentResult(
  payload: Record<string, unknown> | null | undefined,
): ParsedScientificResult | null {
  const root = asRecord(payload)
  if (!root) return null

  const stages = asArray(root.stages)
    .map((item): ParsedStageReport | null => {
      const st = asRecord(item)
      if (!st) return null
      return {
        stageName: asString(st.stage_name ?? st.stageName),
        priority: asString(st.priority),
        status: asString(st.status),
        durationMs: asNumber(st.duration_ms ?? st.durationMs) ?? 0,
        skipReason: asOptionalString(st.skip_reason ?? st.skipReason),
        warnings: asStringList(st.warnings),
        errors: asStringList(st.errors),
      }
    })
    .filter((item): item is ParsedStageReport => item !== null)

  const qualityReports = asArray(root.quality_reports ?? root.qualityReports)
    .map((item): ParsedQualityReport | null => {
      const qr = asRecord(item)
      if (!qr) return null
      return {
        datasetId: asString(qr.dataset_id ?? qr.datasetId),
        variableName: asString(qr.variable_name ?? qr.variableName),
        totalSteps: asNumber(qr.total_steps ?? qr.totalSteps) ?? 0,
        validSteps: asNumber(qr.valid_steps ?? qr.validSteps) ?? 0,
        missingSteps: asNumber(qr.missing_steps ?? qr.missingSteps) ?? 0,
        validFraction: asNumber(qr.valid_fraction ?? qr.validFraction) ?? 0,
        missingFraction: asNumber(qr.missing_fraction ?? qr.missingFraction) ?? 0,
        qaScreenedOutCount: asNumber(qr.qa_screened_out_count ?? qr.qaScreenedOutCount) ?? 0,
        outOfRangeCount: asNumber(qr.out_of_range_count ?? qr.outOfRangeCount) ?? 0,
        warnings: asStringList(qr.warnings),
      }
    })
    .filter((item): item is ParsedQualityReport => item !== null)

  const temporalSeries = asArray(root.temporal_series ?? root.temporalSeries)
    .map((item): ParsedTemporalSeries | null => {
      const ts = asRecord(item)
      if (!ts) return null
      return {
        datasetId: asString(ts.dataset_id ?? ts.datasetId),
        variableName: asString(ts.variable_name ?? ts.variableName),
        units: asString(ts.units),
        cadence: asString(ts.cadence),
        aggregationOperator: asString(ts.aggregation_operator ?? ts.aggregationOperator),
        timestamps: asStringList(ts.timestamps),
        values: asArray(ts.values).map((v) => asNumber(v)),
        coverageFractions: asArray(ts.coverage_fractions ?? ts.coverageFractions).map((v) =>
          asNumber(v),
        ),
        interpolatedIndices: asArray(ts.interpolated_indices ?? ts.interpolatedIndices)
          .map((v) => asNumber(v))
          .filter((v): v is number => v !== null),
        warnings: asStringList(ts.warnings),
      }
    })
    .filter((item): item is ParsedTemporalSeries => item !== null)

  const baselines = asArray(root.baselines)
    .map((item): ParsedBaselineClimatology | null => {
      const bl = asRecord(item)
      if (!bl) return null
      return {
        datasetId: asString(bl.dataset_id ?? bl.datasetId),
        variableName: asString(bl.variable_name ?? bl.variableName),
        units: asString(bl.units),
        baselineType: asString(bl.baseline_type ?? bl.baselineType),
        binMeans: asArray(bl.bin_means ?? bl.binMeans).map((v) => asNumber(v)),
        binStds: asArray(bl.bin_stds ?? bl.binStds).map((v) => asNumber(v)),
        binCounts: asArray(bl.bin_counts ?? bl.binCounts)
          .map((v) => asNumber(v))
          .filter((v): v is number => v !== null),
        warnings: asStringList(bl.warnings),
      }
    })
    .filter((item): item is ParsedBaselineClimatology => item !== null)

  const anomalies = asArray(root.anomalies)
    .map((item): ParsedAnomalySeries | null => {
      const an = asRecord(item)
      if (!an) return null
      const runs = asArray(an.persistent_runs ?? an.persistentRuns)
        .map((r): ParsedPersistentRun | null => {
          const rec = asRecord(r)
          if (!rec) return null
          return {
            startTimestamp: asString(rec.start_timestamp ?? rec.startTimestamp),
            endTimestamp: asString(rec.end_timestamp ?? rec.endTimestamp),
            durationSteps: asNumber(rec.duration_steps ?? rec.durationSteps) ?? 0,
            peakZscore: asNumber(rec.peak_zscore ?? rec.peakZscore) ?? 0,
            severity: asString(rec.severity),
          }
        })
        .filter((r): r is ParsedPersistentRun => r !== null)
      return {
        datasetId: asString(an.dataset_id ?? an.datasetId),
        variableName: asString(an.variable_name ?? an.variableName),
        units: asString(an.units),
        timestamps: asStringList(an.timestamps),
        rawAnomalies: asArray(an.raw_anomalies ?? an.rawAnomalies).map((v) => asNumber(v)),
        standardZscores: asArray(an.standard_zscores ?? an.standardZscores).map((v) =>
          asNumber(v),
        ),
        robustZscores: asArray(an.robust_zscores ?? an.robustZscores).map((v) => asNumber(v)),
        persistentRuns: runs,
        warnings: asStringList(an.warnings),
      }
    })
    .filter((item): item is ParsedAnomalySeries => item !== null)

  const crossVariable = asArray(root.cross_variable ?? root.crossVariable)
    .map((item): ParsedCrossVariableResult | null => {
      const cv = asRecord(item)
      if (!cv) return null
      return {
        xVariable: asString(cv.x_variable ?? cv.xVariable),
        yVariable: asString(cv.y_variable ?? cv.yVariable),
        pearsonR: asNumber(cv.pearson_r ?? cv.pearsonR),
        spearmanRho: asNumber(cv.spearman_rho ?? cv.spearmanRho),
        lagSteps: asNumber(cv.lag_steps ?? cv.lagSteps) ?? 0,
        pValue: asNumber(cv.p_value ?? cv.pValue),
        sampleCount: asNumber(cv.sample_count ?? cv.sampleCount) ?? 0,
        caveat: asString(
          cv.caveat,
          'Statistical association only; correlation does not establish causation.',
        ),
        warnings: asStringList(cv.warnings),
      }
    })
    .filter((item): item is ParsedCrossVariableResult => item !== null)

  const trends = asArray(root.trends)
    .map((item): ParsedTrendSummary | null => {
      const tr = asRecord(item)
      if (!tr) return null
      return {
        datasetId: asString(tr.dataset_id ?? tr.datasetId),
        variableName: asString(tr.variable_name ?? tr.variableName),
        variant: asString(tr.variant),
        sampleCount: asNumber(tr.sample_count ?? tr.sampleCount) ?? 0,
        validCount: asNumber(tr.valid_count ?? tr.validCount) ?? 0,
        direction: asString(tr.direction),
        pValue: asNumber(tr.p_value ?? tr.pValue),
        sensSlope: asNumber(tr.sens_slope ?? tr.sensSlope),
        slopeUnit: asString(tr.slope_unit ?? tr.slopeUnit),
        warnings: asStringList(tr.warnings),
      }
    })
    .filter((item): item is ParsedTrendSummary => item !== null)

  const recoveries = asArray(root.recoveries)
    .map((item): ParsedRecoveryEvent | null => {
      const ev = asRecord(item)
      if (!ev) return null
      return {
        datasetId: asString(ev.dataset_id ?? ev.datasetId),
        variableName: asString(ev.variable_name ?? ev.variableName),
        eventStart: asString(ev.event_start ?? ev.eventStart),
        eventPeakTimestamp: asString(ev.event_peak_timestamp ?? ev.eventPeakTimestamp),
        observationEnd: asString(ev.observation_end ?? ev.observationEnd),
        deficitMagnitude: asNumber(ev.deficit_magnitude ?? ev.deficitMagnitude) ?? 0,
        timeToRecoveryDays: asNumber(ev.time_to_recovery_days ?? ev.timeToRecoveryDays),
        recoveryCompleteness: asNumber(ev.recovery_completeness ?? ev.recoveryCompleteness) ?? 0,
        elapsedRecoveryRate: asNumber(ev.elapsed_recovery_rate ?? ev.elapsedRecoveryRate),
        rateUnit: asString(ev.rate_unit ?? ev.rateUnit),
        status: asString(ev.status),
        seasonalCaveat: asString(ev.seasonal_caveat ?? ev.seasonalCaveat),
        warnings: asStringList(ev.warnings),
      }
    })
    .filter((item): item is ParsedRecoveryEvent => item !== null)

  const resilience = asArray(root.resilience)
    .map((item): ParsedResilienceSummary | null => {
      const res = asRecord(item)
      if (!res) return null
      const tri = asRecord(res.composite_tri ?? res.compositeTri)
      return {
        datasetId: asString(res.dataset_id ?? res.datasetId),
        variableName: asString(res.variable_name ?? res.variableName),
        resistance: parseResilienceDimension(res.resistance),
        recovery: parseResilienceDimension(res.recovery),
        stability: parseResilienceDimension(res.stability),
        sensitivity: parseResilienceDimension(res.sensitivity),
        compositeTriStatus: asString(tri?.status, 'unavailable_unvalidated'),
        compositeTriReason: asString(tri?.reason),
      }
    })
    .filter((item): item is ParsedResilienceSummary => item !== null)

  const unc = asRecord(root.uncertainty)
  const uncertainty: ParsedUncertaintySummary | null = unc
    ? {
        dataQualityConfidence: asString(
          unc.data_quality_confidence ?? unc.dataQualityConfidence,
          'unknown',
        ),
        dataQualityRationale: asString(unc.data_quality_rationale ?? unc.dataQualityRationale),
        statisticalConfidence: asString(
          unc.statistical_confidence ?? unc.statisticalConfidence,
          'unknown',
        ),
        statisticalRationale: asString(unc.statistical_rationale ?? unc.statisticalRationale),
        scientificConfidence: asString(
          unc.scientific_confidence ?? unc.scientificConfidence,
          'unknown',
        ),
        scientificRationale: asString(unc.scientific_rationale ?? unc.scientificRationale),
        methodologicalLimitations: asStringList(
          unc.methodological_limitations ?? unc.methodologicalLimitations,
        ),
      }
    : null

  const prov = asRecord(root.provenance)
  const provenance: ParsedProvenanceRecord | null = prov
    ? {
        inputDigestSha256: asString(prov.input_digest_sha256 ?? prov.inputDigestSha256),
        configDigestSha256: asString(prov.config_digest_sha256 ?? prov.configDigestSha256),
        generatedAtUtc: asString(prov.generated_at_utc ?? prov.generatedAtUtc),
        datasetLineage: asArray(prov.dataset_lineage ?? prov.datasetLineage)
          .map((item) => asRecord(item))
          .filter((item): item is Record<string, unknown> => item !== null),
        methodsInvoked: asArray(prov.methods_invoked ?? prov.methodsInvoked)
          .map((item) => {
            const m = asRecord(item)
            if (!m) return null
            return {
              methodId: asString(m.method_id ?? m.methodId),
              version: asString(m.version),
              name: asString(m.name),
            }
          })
          .filter((item): item is { methodId: string; version: string; name: string } => item !== null),
        packageVersions: Object.fromEntries(
          Object.entries(asRecord(prov.package_versions ?? prov.packageVersions) ?? {}).filter(
            (entry): entry is [string, string] => typeof entry[1] === 'string',
          ),
        ),
      }
    : null

  return {
    assessmentId: asString(root.assessment_id ?? root.assessmentId),
    status: asString(root.status),
    stages,
    qualityReports,
    temporalSeries,
    baselines,
    anomalies,
    trends,
    recoveries,
    crossVariable,
    resilience,
    uncertainty,
    provenance,
    warnings: asStringList(root.warnings),
    errors: asStringList(root.errors),
  }
}

export async function fetchAssessmentMethods(): Promise<MethodCatalogItemResponse[]> {
  try {
    const result = await apiFetchClient.GET('/api/v1/assessments/methods')
    return unwrapApiResponse(result, 'GET /api/v1/assessments/methods')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /api/v1/assessments/methods: ${String(cause)}`)
  }
}

export async function fetchAssessments(): Promise<AssessmentSummaryResponse[]> {
  try {
    const result = await apiFetchClient.GET('/api/v1/assessments')
    return unwrapApiResponse(result, 'GET /api/v1/assessments')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling /api/v1/assessments: ${String(cause)}`)
  }
}

export async function fetchAssessmentDetail(
  assessmentId: string,
): Promise<AssessmentDetailResponse> {
  try {
    const result = await apiFetchClient.GET('/api/v1/assessments/{assessment_id}', {
      params: { path: { assessment_id: assessmentId } },
    })
    return unwrapApiResponse(result, `GET /api/v1/assessments/${assessmentId}`)
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(
      0,
      `Network error calling /api/v1/assessments/${assessmentId}: ${String(cause)}`,
    )
  }
}

export async function createAssessment(
  body: CreateAssessmentRequest,
): Promise<AssessmentDetailResponse> {
  try {
    const result = await apiFetchClient.POST('/api/v1/assessments', { body })
    return unwrapApiResponse(result, 'POST /api/v1/assessments')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling POST /api/v1/assessments: ${String(cause)}`)
  }
}

export async function executeAssessment(
  assessmentId: string,
): Promise<AssessmentDetailResponse> {
  try {
    const result = await apiFetchClient.POST('/api/v1/assessments/{assessment_id}/execute', {
      params: { path: { assessment_id: assessmentId } },
    })
    return unwrapApiResponse(result, `POST /api/v1/assessments/${assessmentId}/execute`)
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(
      0,
      `Network error calling POST /api/v1/assessments/${assessmentId}/execute: ${String(cause)}`,
    )
  }
}

export function useAssessmentMethodsQuery() {
  return useQuery({
    queryKey: ASSESSMENT_METHODS_QUERY_KEY,
    queryFn: fetchAssessmentMethods,
    staleTime: 5 * 60_000,
    retry: 1,
  })
}

export function useAssessmentsQuery(enabled = true) {
  return useQuery({
    queryKey: ASSESSMENTS_LIST_QUERY_KEY,
    queryFn: fetchAssessments,
    enabled,
    staleTime: 15_000,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        return false
      }
      return failureCount < 1
    },
  })
}

export function useAssessmentDetailQuery(assessmentId: string | null, enabled = true) {
  return useQuery({
    queryKey: assessmentDetailQueryKey(assessmentId ?? ''),
    queryFn: () => {
      if (!assessmentId) {
        throw new ApiError(400, 'Assessment ID is required')
      }
      return fetchAssessmentDetail(assessmentId)
    },
    enabled: Boolean(assessmentId) && enabled,
    staleTime: 5_000,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? 2500 : false
    },
    retry: (failureCount, error) => {
      if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
        return false
      }
      return failureCount < 1
    },
  })
}

export function useCreateAssessmentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createAssessment,
    onSuccess: (detail) => {
      queryClient.setQueryData(assessmentDetailQueryKey(detail.id), detail)
      void queryClient.invalidateQueries({ queryKey: ASSESSMENTS_LIST_QUERY_KEY })
    },
  })
}

export function useExecuteAssessmentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: executeAssessment,
    onSuccess: (detail) => {
      queryClient.setQueryData(assessmentDetailQueryKey(detail.id), detail)
      void queryClient.invalidateQueries({ queryKey: ASSESSMENTS_LIST_QUERY_KEY })
    },
  })
}

export async function compareAssessments(
  body: CompareAssessmentsRequest,
): Promise<AssessmentComparisonResponse> {
  try {
    const result = await apiFetchClient.POST('/api/v1/assessments/compare', { body })
    return unwrapApiResponse(result, 'POST /api/v1/assessments/compare')
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    throw new ApiError(0, `Network error calling POST /api/v1/assessments/compare: ${String(cause)}`)
  }
}

export function useCompareAssessmentsMutation() {
  return useMutation({
    mutationFn: compareAssessments,
  })
}
