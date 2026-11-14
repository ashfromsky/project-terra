import { useState } from 'react'
import { useNavigate } from 'react-router'
import { figmaAssets } from '../../shared/config/assets'
import { APP_ROUTES } from '../../shared/config/routes'
import {
  useUiStore,
  type TemporalCadence,
  type WorkspaceTab,
} from '../../shared/store/ui-store'

interface CorrelationCell {
  row: number
  col: number
  value: string
  bg: string
  color: string
  left: number
  top: number
  textLeft: number
  nodeId: string
}

const CORRELATION_CELLS: readonly CorrelationCell[] = [
  { row: 0, col: 0, value: '1.00', bg: '#e7f3f1', color: '#315f59', left: 53, top: 71, textLeft: 13, nodeId: '5:347' },
  { row: 0, col: 1, value: '-0.62', bg: '#e9d1c7', color: '#805f51', left: 105, top: 71, textLeft: 10, nodeId: '5:349' },
  { row: 0, col: 2, value: '-0.44', bg: '#f0dfd7', color: '#805f51', left: 157, top: 71, textLeft: 10, nodeId: '5:351' },
  { row: 0, col: 3, value: '-0.57', bg: '#ecd6cb', color: '#805f51', left: 209, top: 71, textLeft: 10, nodeId: '5:353' },

  { row: 1, col: 0, value: '-0.62', bg: '#e9d1c7', color: '#805f51', left: 53, top: 96, textLeft: 10, nodeId: '5:355' },
  { row: 1, col: 1, value: '1.00', bg: '#e7f3f1', color: '#315f59', left: 105, top: 96, textLeft: 13, nodeId: '5:357' },
  { row: 1, col: 2, value: '0.58', bg: '#c6e4df', color: '#315f59', left: 157, top: 96, textLeft: 13, nodeId: '5:359' },
  { row: 1, col: 3, value: '0.66', bg: '#b9ded7', color: '#315f59', left: 209, top: 96, textLeft: 13, nodeId: '5:361' },

  { row: 2, col: 0, value: '-0.44', bg: '#f0dfd7', color: '#805f51', left: 53, top: 121, textLeft: 10, nodeId: '5:363' },
  { row: 2, col: 1, value: '0.58', bg: '#c6e4df', color: '#315f59', left: 105, top: 121, textLeft: 13, nodeId: '5:365' },
  { row: 2, col: 2, value: '1.00', bg: '#e7f3f1', color: '#315f59', left: 157, top: 121, textLeft: 13, nodeId: '5:367' },
  { row: 2, col: 3, value: '0.79', bg: '#91c9bf', color: '#315f59', left: 209, top: 121, textLeft: 13, nodeId: '5:369' },

  { row: 3, col: 0, value: '-0.57', bg: '#ecd6cb', color: '#805f51', left: 53, top: 146, textLeft: 10, nodeId: '5:371' },
  { row: 3, col: 1, value: '0.66', bg: '#b9ded7', color: '#315f59', left: 105, top: 146, textLeft: 13, nodeId: '5:373' },
  { row: 3, col: 2, value: '0.79', bg: '#91c9bf', color: '#315f59', left: 157, top: 146, textLeft: 13, nodeId: '5:375' },
  { row: 3, col: 3, value: '1.00', bg: '#e7f3f1', color: '#315f59', left: 209, top: 146, textLeft: 13, nodeId: '5:377' },
]

const CADENCE_OPTIONS: readonly TemporalCadence[] = ['Monthly', 'Seasonal', 'Annual']

export function AnalyticsWorkspaceSection() {
  const navigate = useNavigate()
  const selectedRegion = useUiStore((state) => state.selectedRegion)
  const activeWorkspaceTab = useUiStore((state) => state.activeWorkspaceTab)
  const setActiveWorkspaceTab = useUiStore((state) => state.setActiveWorkspaceTab)
  const timelinePlaying = useUiStore((state) => state.timelinePlaying)
  const toggleTimelinePlaying = useUiStore((state) => state.toggleTimelinePlaying)
  const temporalCadence = useUiStore((state) => state.temporalCadence)
  const setTemporalCadence = useUiStore((state) => state.setTemporalCadence)

  const [cadenceMenuOpen, setCadenceMenuOpen] = useState(false)

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
              Example data
            </span>
          </span>

          <button
            type="button"
            className="analytics-workspace__export-btn"
            data-node-id="5:278"
            onClick={() => navigate(APP_ROUTES.reports)}
          >
            <span className="analytics-workspace__export-icon" data-node-id="5:279">
              <img src={figmaAssets.download} alt="" />
            </span>
            <span className="analytics-workspace__export-text" data-node-id="5:282">
              Export analysis
            </span>
          </button>
        </div>

        <div className="analytics-workspace__kpi-grid">
          <article className="kpi-card kpi-card--1" data-node-id="5:283">
            <p className="kpi-card__eyebrow" data-node-id="5:284">
              WARMING TREND
            </p>
            <p className="kpi-card__value" data-node-id="5:285">
              +0.26
            </p>
            <p className="kpi-card__unit kpi-card__unit--1" data-node-id="5:286">
              °C / decade
            </p>
            <p className="kpi-card__status kpi-card__status--coral" data-node-id="5:287">
              ↑  Positive trend
            </p>
          </article>

          <article className="kpi-card kpi-card--2" data-node-id="5:288">
            <p className="kpi-card__eyebrow" data-node-id="5:289">
              95% CONFIDENCE INTERVAL
            </p>
            <p className="kpi-card__value kpi-card__value--range" data-node-id="5:290">
              0.22 — 0.30
            </p>
            <p className="kpi-card__unit kpi-card__unit--2" data-node-id="5:291">
              °C / decade
            </p>
            <p className="kpi-card__status" data-node-id="5:292">
              OLS · Seasonally adjusted
            </p>
          </article>

          <article className="kpi-card kpi-card--3" data-node-id="5:293">
            <p className="kpi-card__eyebrow" data-node-id="5:294">
              STATISTICAL SIGNIFICANCE
            </p>
            <p className="kpi-card__value" data-node-id="5:295">
              p &lt; 0.001
            </p>
            <p className="kpi-card__status kpi-card__status--teal" data-node-id="5:296">
              Significant at α = 0.05
            </p>
          </article>

          <article className="kpi-card kpi-card--4" data-node-id="5:297">
            <p className="kpi-card__eyebrow" data-node-id="5:298">
              OBSERVATION COVERAGE
            </p>
            <p className="kpi-card__value" data-node-id="5:299">
              96.8
            </p>
            <p className="kpi-card__unit kpi-card__unit--4" data-node-id="5:300">
              %
            </p>
            <p className="kpi-card__status" data-node-id="5:301">
              300 months · Quality screened
            </p>
          </article>
        </div>

        <div className="analytics-workspace__panels-row">
          <article className="timeseries-card" data-node-id="5:302">
            <p className="timeseries-card__title" data-node-id="5:303">
              Land surface temperature anomaly
            </p>
            <p className="timeseries-card__subtitle" data-node-id="5:304">
              Annual display · Monthly OLS · Baseline 2001–2010
            </p>
            <div className="timeseries-card__legend-graphic" data-node-id="5:305">
              <img src={figmaAssets.chartLegend} alt="" />
            </div>
            <p className="timeseries-card__legend-label" style={{ left: '401px' }} data-node-id="5:309">
              Observed
            </p>
            <p className="timeseries-card__legend-label" style={{ left: '496px' }} data-node-id="5:310">
              OLS trend
            </p>
            <p className="timeseries-card__legend-label" style={{ left: '599px' }} data-node-id="5:311">
              95% CI
            </p>

            <p className="timeseries-card__y-label" style={{ top: '47px' }} data-node-id="5:335">
              °C
            </p>
            <p className="timeseries-card__y-label" style={{ top: '53px' }} data-node-id="5:317">
              0.8
            </p>
            <p className="timeseries-card__y-label" style={{ top: '73.8px' }} data-node-id="5:316">
              0.6
            </p>
            <p className="timeseries-card__y-label" style={{ top: '94.6px' }} data-node-id="5:315">
              0.4
            </p>
            <p className="timeseries-card__y-label" style={{ top: '115.4px' }} data-node-id="5:314">
              0.2
            </p>
            <p className="timeseries-card__y-label" style={{ top: '136.2px' }} data-node-id="5:313">
              0.0
            </p>
            <p className="timeseries-card__y-label" style={{ top: '157px' }} data-node-id="5:312">
              -0.2
            </p>

            <div className="timeseries-card__series" data-node-id="5:318">
              <img
                src={figmaAssets.observedTrendSeries}
                alt="Observed LST anomaly trend, OLS regression, and 95% confidence interval"
              />
            </div>

            <p className="timeseries-card__x-label" style={{ left: '39px' }} data-node-id="5:329">
              2001
            </p>
            <p className="timeseries-card__x-label" style={{ left: '140.17px' }} data-node-id="5:330">
              2005
            </p>
            <p className="timeseries-card__x-label" style={{ left: '266.63px' }} data-node-id="5:331">
              2010
            </p>
            <p className="timeseries-card__x-label" style={{ left: '393.08px' }} data-node-id="5:332">
              2015
            </p>
            <p className="timeseries-card__x-label" style={{ left: '519.54px' }} data-node-id="5:333">
              2020
            </p>
            <p className="timeseries-card__x-label" style={{ left: '646px' }} data-node-id="5:334">
              2025
            </p>
          </article>

          <article className="correlation-card" data-node-id="5:336">
            <p className="correlation-card__title" data-node-id="5:337">
              Earth system correlations
            </p>
            <p className="correlation-card__subtitle" data-node-id="5:338">
              Pearson r · Monthly regional means
            </p>

            <p className="correlation-card__col-label" style={{ left: '62px' }} data-node-id="5:339">
              LST
            </p>
            <p className="correlation-card__col-label" style={{ left: '114px' }} data-node-id="5:341">
              NDVI
            </p>
            <p className="correlation-card__col-label" style={{ left: '166px' }} data-node-id="5:343">
              Precip.
            </p>
            <p className="correlation-card__col-label" style={{ left: '218px' }} data-node-id="5:345">
              Soil
            </p>

            <p className="correlation-card__row-label" style={{ top: '78px' }} data-node-id="5:340">
              LST
            </p>
            <p className="correlation-card__row-label" style={{ top: '103px' }} data-node-id="5:342">
              NDVI
            </p>
            <p className="correlation-card__row-label" style={{ top: '128px' }} data-node-id="5:344">
              Precip.
            </p>
            <p className="correlation-card__row-label" style={{ top: '153px' }} data-node-id="5:346">
              Soil
            </p>

            {CORRELATION_CELLS.map((cell) => (
              <div
                key={`${cell.row}-${cell.col}`}
                className="correlation-card__cell"
                style={{
                  left: `${cell.left}px`,
                  top: `${cell.top}px`,
                  backgroundColor: cell.bg,
                }}
                data-node-id={cell.nodeId}
              >
                <span
                  className="correlation-card__cell-text"
                  style={{ left: `${cell.textLeft}px`, color: cell.color }}
                >
                  {cell.value}
                </span>
              </div>
            ))}

            <p className="correlation-card__scale-min" data-node-id="5:379">
              −1
            </p>
            <div className="correlation-card__scale-bar" data-node-id="5:380" />
            <p className="correlation-card__scale-max" data-node-id="5:381">
              +1
            </p>
          </article>

          <article className="insights-card" data-node-id="5:382">
            <div className="insights-card__icon" data-node-id="5:383">
              <img src={figmaAssets.scientificAnalysis} alt="" />
            </div>
            <p className="insights-card__title" data-node-id="5:388">
              Terra intelligence
            </p>
            <div className="insights-card__ai-pill" data-node-id="5:389" />
            <p className="insights-card__ai-text" data-node-id="5:390">
              AI GENERATED
            </p>
            <p className="insights-card__headline" data-node-id="5:391">
              A persistent warming signal
            </p>
            <p className="insights-card__body" data-node-id="5:392">
              Global land surface temperature rises by 0.26°C per decade. The 95% interval excludes zero, supporting a robust positive trend.
            </p>
            <div className="insights-card__divider" data-node-id="5:393" />
            <p className="insights-card__subhead" data-node-id="5:394">
              LST and vegetation move in opposite directions
            </p>
            <p className="insights-card__disclaimer" data-node-id="5:395">
              r = −0.62 · Correlation does not establish causation.
            </p>
            <button
              type="button"
              className="insights-card__link"
              data-node-id="5:396"
              onClick={() => navigate(APP_ROUTES.assessments)}
            >
              Review supporting evidence  ↗
            </button>
          </article>
        </div>

        <div className="timeline-bar" data-node-id="5:397">
          <button
            type="button"
            className={`timeline-bar__play-btn ${
              timelinePlaying ? 'timeline-bar__play-btn--active' : ''
            }`}
            data-node-id="5:398"
            aria-label={timelinePlaying ? 'Pause observation timeline' : 'Play observation timeline'}
            aria-pressed={timelinePlaying}
            onClick={toggleTimelinePlaying}
          >
            <span className="timeline-bar__play-icon" data-node-id="5:399">
              <img src={figmaAssets.play} alt="" />
            </span>
          </button>

          <p className="timeline-bar__year-start" data-node-id="5:401">
            2001
          </p>

          <div className="timeline-bar__histogram" data-node-id="5:402">
            <img src={figmaAssets.monthlyObservationTimeline} alt="Monthly observation coverage 2001 to 2025" />
          </div>

          <div
            className="timeline-bar__handle timeline-bar__handle--start"
            data-node-id="5:504"
            role="slider"
            tabIndex={0}
            aria-label="Observation period start handle"
            aria-valuemin={2001}
            aria-valuemax={2025}
            aria-valuenow={2001}
          />
          <div
            className="timeline-bar__handle timeline-bar__handle--end"
            data-node-id="5:505"
            role="slider"
            tabIndex={0}
            aria-label="Observation period end handle"
            aria-valuemin={2001}
            aria-valuemax={2025}
            aria-valuenow={2025}
          />

          <p className="timeline-bar__year-end" data-node-id="5:506">
            2025
          </p>

          <div className="timeline-bar__separator" data-node-id="5:507" />

          <button
            type="button"
            className="timeline-bar__cadence-btn"
            onClick={() => setCadenceMenuOpen((open) => !open)}
            aria-expanded={cadenceMenuOpen}
            aria-label="Temporal aggregation cadence"
          >
            <span className="timeline-bar__cadence-text" data-node-id="5:508">
              {temporalCadence}
            </span>
            <span className="timeline-bar__cadence-chevron" data-node-id="5:509">
              <img src={figmaAssets.timelineInterval} alt="" />
            </span>
          </button>

          {cadenceMenuOpen && (
            <ul className="timeline-bar__cadence-menu" role="listbox">
              {CADENCE_OPTIONS.map((option) => (
                <li key={option}>
                  <button
                    type="button"
                    className="timeline-bar__cadence-option"
                    onClick={() => {
                      setTemporalCadence(option)
                      setCadenceMenuOpen(false)
                    }}
                  >
                    {option}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <p className="analytics-workspace__footer-left" data-node-id="5:511">
          NASA MODIS Terra / MOD11C3   ·   Daytime LST   ·   QC-filtered monthly composites
        </p>
        <p className="analytics-workspace__footer-right" data-node-id="5:512">
          Concept demonstration · Not for operational decisions
        </p>
      </div>
    </section>
  )
}
