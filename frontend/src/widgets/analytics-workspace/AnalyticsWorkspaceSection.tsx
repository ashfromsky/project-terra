import { useMemo } from 'react'
import { useNavigate } from 'react-router'
import {
  parseScientificAssessmentResult,
  useAssessmentDetailQuery,
  useAssessmentsQuery,
} from '../../shared/api/assessments'
import { useCurrentUserQuery } from '../../shared/api/auth'
import { useLayerCatalogQuery } from '../../shared/api/layers'
import { figmaAssets } from '../../shared/config/assets'
import { APP_ROUTES } from '../../shared/config/routes'
import { useUiStore, type WorkspaceTab } from '../../shared/store/ui-store'

export function AnalyticsWorkspaceSection() {
  const navigate = useNavigate()
  const selectedRegion = useUiStore((state) => state.selectedRegion)
  const activeWorkspaceTab = useUiStore((state) => state.activeWorkspaceTab)
  const setActiveWorkspaceTab = useUiStore((state) => state.setActiveWorkspaceTab)

  const currentUserQuery = useCurrentUserQuery()
  const isAuthenticated = Boolean(currentUserQuery.data)
  const layersQuery = useLayerCatalogQuery()
  const assessmentsQuery = useAssessmentsQuery(isAuthenticated)

  const latestCompleted = useMemo(() => {
    const list = assessmentsQuery.data ?? []
    return (
      list.find(
        (item) => item.status === 'completed' || item.status === 'completed_partial',
      ) ?? null
    )
  }, [assessmentsQuery.data])

  const detailQuery = useAssessmentDetailQuery(
    latestCompleted?.id ?? null,
    isAuthenticated && Boolean(latestCompleted),
  )

  const parsed = useMemo(() => {
    const payload = detailQuery.data?.result as Record<string, unknown> | null | undefined
    return parseScientificAssessmentResult(payload)
  }, [detailQuery.data?.result])

  const layers = layersQuery.data ?? []
  const connectedLayersCount = layers.filter(
    (item) => item.availabilityStatus === 'connected',
  ).length

  const primaryTrend = parsed?.trends[0] ?? null
  const primaryQuality = parsed?.qualityReports[0] ?? null
  const primarySeries = parsed?.temporalSeries[0] ?? null
  const crossVarList = parsed?.crossVariable ?? []

  function handleTabSelection(tab: WorkspaceTab) {
    setActiveWorkspaceTab(tab)
  }

  return (
    <section
      className="analytics-workspace"
      data-node-id="5:113"
      aria-label="Analysis workspace"
    >
      <div className="analytics-workspace__top-border" data-node-id="5:268" />
      <div className="analytics-workspace__inner">
        <div className="analytics-workspace__header">
          <h2 className="analytics-workspace__title" data-node-id="5:269">
            Analysis workspace
          </h2>
          <span className="analytics-workspace__region-badge" data-node-id="5:270">
            <span className="analytics-workspace__region-badge-text" data-node-id="5:271">
              {selectedRegion}
            </span>
          </span>

          <div
            className="analytics-workspace__tabs"
            role="tablist"
            aria-label="Analysis workspace views"
          >
            <button
              type="button"
              role="tab"
              aria-selected={activeWorkspaceTab === 'Overview'}
              className={`analytics-workspace__tab analytics-workspace__tab--overview ${
                activeWorkspaceTab === 'Overview'
                  ? 'analytics-workspace__tab--active'
                  : ''
              }`}
              data-node-id="5:272"
              onClick={() => handleTabSelection('Overview')}
            >
              Overview
              {activeWorkspaceTab === 'Overview' && (
                <span
                  className="analytics-workspace__tab-bar analytics-workspace__tab-bar--overview"
                  data-node-id="5:273"
                />
              )}
            </button>

            <button
              type="button"
              role="tab"
              aria-selected={activeWorkspaceTab === 'Regional comparison'}
              className={`analytics-workspace__tab analytics-workspace__tab--comparison ${
                activeWorkspaceTab === 'Regional comparison'
                  ? 'analytics-workspace__tab--active'
                  : ''
              }`}
              data-node-id="5:274"
              onClick={() => {
                handleTabSelection('Regional comparison')
                navigate(APP_ROUTES.comparativeAnalysis)
              }}
            >
              Regional comparison
              {activeWorkspaceTab === 'Regional comparison' && (
                <span className="analytics-workspace__tab-bar" />
              )}
            </button>

            <button
              type="button"
              role="tab"
              aria-selected={activeWorkspaceTab === 'Methods & quality'}
              className={`analytics-workspace__tab analytics-workspace__tab--methods ${
                activeWorkspaceTab === 'Methods & quality'
                  ? 'analytics-workspace__tab--active'
                  : ''
              }`}
              data-node-id="5:275"
              onClick={() => {
                handleTabSelection('Methods & quality')
                navigate(APP_ROUTES.dataSources)
              }}
            >
              Methods &amp; quality
              {activeWorkspaceTab === 'Methods & quality' && (
                <span className="analytics-workspace__tab-bar" />
              )}
            </button>
          </div>

          <span className="analytics-workspace__sample-pill" data-node-id="5:276">
            <span className="analytics-workspace__sample-text" data-node-id="5:277">
              {latestCompleted
                ? `Live · ${latestCompleted.status}`
                : isAuthenticated
                  ? 'No completed assessments'
                  : 'Sign in for assessments'}
            </span>
          </span>

          <button
            type="button"
            className="analytics-workspace__export-btn"
            data-node-id="5:278"
            onClick={() => navigate(APP_ROUTES.assessments)}
          >
            <span className="analytics-workspace__export-icon" data-node-id="5:279">
              <img src={figmaAssets.download} alt="" />
            </span>
            <span className="analytics-workspace__export-text" data-node-id="5:282">
              Open assessments
            </span>
          </button>
        </div>

        <div className="analytics-workspace__kpi-grid">
          <article className="kpi-card kpi-card--1" data-node-id="5:283">
            <p className="kpi-card__eyebrow" data-node-id="5:284">
              PRIMARY TREND SLOPE
            </p>
            <p className="kpi-card__value" data-node-id="5:285">
              {primaryTrend?.sensSlope !== null && primaryTrend?.sensSlope !== undefined
                ? `${primaryTrend.sensSlope >= 0 ? '+' : ''}${primaryTrend.sensSlope.toFixed(4)}`
                : '—'}
            </p>
            <p className="kpi-card__unit kpi-card__unit--1" data-node-id="5:286">
              {primaryTrend ? primaryTrend.slopeUnit : 'Unavailable'}
            </p>
            <p className="kpi-card__status" data-node-id="5:287">
              {primaryTrend
                ? `${primaryTrend.variableName} · ${primaryTrend.direction}`
                : 'Run a scientific assessment'}
            </p>
          </article>

          <article className="kpi-card kpi-card--2" data-node-id="5:288">
            <p className="kpi-card__eyebrow" data-node-id="5:289">
              CONNECTED MAP LAYERS
            </p>
            <p className="kpi-card__value kpi-card__value--range" data-node-id="5:290">
              {`${connectedLayersCount} / ${layers.length}`}
            </p>
            <p className="kpi-card__unit kpi-card__unit--2" data-node-id="5:291">
              COG layers
            </p>
            <p className="kpi-card__status" data-node-id="5:292">
              {connectedLayersCount > 0
                ? 'Backend raster tiles active'
                : 'Ingest observations in Data Sources'}
            </p>
          </article>

          <article className="kpi-card kpi-card--3" data-node-id="5:293">
            <p className="kpi-card__eyebrow" data-node-id="5:294">
              STATISTICAL SIGNIFICANCE
            </p>
            <p className="kpi-card__value" data-node-id="5:295">
              {primaryTrend?.pValue !== null && primaryTrend?.pValue !== undefined
                ? `p = ${primaryTrend.pValue.toFixed(4)}`
                : '—'}
            </p>
            <p className="kpi-card__status kpi-card__status--teal" data-node-id="5:296">
              {primaryTrend?.pValue !== null && primaryTrend?.pValue !== undefined
                ? primaryTrend.pValue < 0.05
                  ? 'Significant at α = 0.05'
                  : 'Not significant at α = 0.05'
                : 'Unavailable until computed'}
            </p>
          </article>

          <article className="kpi-card kpi-card--4" data-node-id="5:297">
            <p className="kpi-card__eyebrow" data-node-id="5:298">
              OBSERVATION COVERAGE
            </p>
            <p className="kpi-card__value" data-node-id="5:299">
              {primaryQuality ? (primaryQuality.validFraction * 100).toFixed(1) : '—'}
            </p>
            <p className="kpi-card__unit kpi-card__unit--4" data-node-id="5:300">
              %
            </p>
            <p className="kpi-card__status" data-node-id="5:301">
              {primaryQuality
                ? `${primaryQuality.validSteps} / ${primaryQuality.totalSteps} steps · Quality screened`
                : 'No quality report available'}
            </p>
          </article>
        </div>

        <div className="analytics-workspace__panels-row">
          <article className="timeseries-card" data-node-id="5:302">
            <p className="timeseries-card__title" data-node-id="5:303">
              {primarySeries
                ? `${primarySeries.variableName} (${primarySeries.units})`
                : 'Assessment temporal coverage'}
            </p>
            <p className="timeseries-card__subtitle" data-node-id="5:304">
              {primarySeries
                ? `${primarySeries.cadence} · ${primarySeries.aggregationOperator} · ${primarySeries.timestamps.length} timestamps (${primarySeries.timestamps[0] ?? ''} to ${primarySeries.timestamps[primarySeries.timestamps.length - 1] ?? ''})`
                : 'No completed assessment time series yet. Discover & ingest NASA observations in Data Sources, then execute an assessment.'}
            </p>
          </article>

          <article className="correlation-card" data-node-id="5:336">
            <p className="correlation-card__title" data-node-id="5:337">
              Cross-variable analysis
            </p>
            <p className="correlation-card__subtitle" data-node-id="5:338">
              {crossVarList.length > 0
                ? `${crossVarList[0].xVariable} vs ${crossVarList[0].yVariable}: r = ${crossVarList[0].pearsonR !== null ? crossVarList[0].pearsonR.toFixed(2) : '—'} (n = ${crossVarList[0].sampleCount})`
                : 'Unavailable — requires multi-variable assessment execution'}
            </p>
          </article>

          <article className="insights-card" data-node-id="5:382">
            <div className="insights-card__icon" data-node-id="5:383">
              <img src={figmaAssets.scientificAnalysis} alt="" />
            </div>
            <p className="insights-card__title" data-node-id="5:388">
              Provenance &amp; workflow
            </p>
            <div className="insights-card__ai-pill" data-node-id="5:389" />
            <p className="insights-card__ai-text" data-node-id="5:390">
              {parsed?.provenance ? 'VERIFIED' : 'BACKEND'}
            </p>
            <p className="insights-card__headline" data-node-id="5:391">
              {latestCompleted
                ? `Assessment ${latestCompleted.id.slice(0, 8)}`
                : 'Scientific pipeline ready'}
            </p>
            <p className="insights-card__body" data-node-id="5:392">
              {parsed?.provenance
                ? `Input SHA-256 ${parsed.provenance.inputDigestSha256.slice(0, 12)} · ${parsed.stages.length} pipeline stages recorded.`
                : 'All map raster tiles, point values, and assessments come exclusively from backend Core + GHS pipelines.'}
            </p>
            <div className="insights-card__divider" data-node-id="5:393" />
            <p className="insights-card__subhead" data-node-id="5:394">
              {connectedLayersCount > 0
                ? `${connectedLayersCount} map raster layer(s) ready in Explorer`
                : 'Zero ingested map raster layers'}
            </p>
            <p className="insights-card__disclaimer" data-node-id="5:395">
              Zero synthetic placeholders · OpenFreeMap vector cartography
            </p>
            <button
              type="button"
              className="insights-card__link"
              data-node-id="5:396"
              onClick={() => navigate(APP_ROUTES.assessments)}
            >
              Review scientific assessments  ↗
            </button>
          </article>
        </div>

        <p className="analytics-workspace__footer-left" data-node-id="5:511">
          TERRA Core · Live layer catalog &amp; scientific assessment records
        </p>
        <p className="analytics-workspace__footer-right" data-node-id="5:512">
          Honest empty/unavailable disclosure · No synthetic data
        </p>
      </div>
    </section>
  )
}
