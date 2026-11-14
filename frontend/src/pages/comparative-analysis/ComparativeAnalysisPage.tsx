import { Link } from 'react-router'
import { Button } from '../../shared/ui/button'
import { StatusBadge } from '../../shared/ui/status-badge'
import { APP_ROUTES } from '../../shared/config/routes'

export default function ComparativeAnalysisPage() {
  return (
    <div className="workspace-page" data-node-id="14:7465">
      <section className="workspace-context-bar" data-node-id="14:7491" aria-label="Analysis context">
        <div className="workspace-context-bar__titles">
          <h1 className="workspace-context-bar__heading" data-node-id="14:7492">
            Ecosystem response &amp; resilience
          </h1>
          <p className="workspace-context-bar__breadcrumb" data-node-id="14:7493">
            Comparative Analysis  /  Drought response  /  Brazil
          </p>
        </div>
        <div className="workspace-context-bar__actions">
          <StatusBadge tone="synthetic">
            SYNTHETIC DATA · Research demonstration
          </StatusBadge>
          <Link to={APP_ROUTES.explore} className="terra-link-reset">
            <Button variant="secondary">New comparison</Button>
          </Link>
          <Link to={APP_ROUTES.assessments} className="terra-link-reset">
            <Button variant="secondary">Assessments</Button>
          </Link>
          <Link to={APP_ROUTES.reports} className="terra-link-reset">
            <Button variant="primary">Export report</Button>
          </Link>
        </div>
      </section>

      <div className="workspace-placeholder-shell">
        <aside
          className="workspace-config-rail"
          data-node-id="14:7499"
          aria-label="Analysis configuration"
        >
          <h2 className="workspace-config-rail__title" data-node-id="14:7500">
            Analysis configuration
          </h2>
          <p className="workspace-config-rail__subtitle" data-node-id="14:7501">
            Compare matched observation windows
          </p>
          <hr className="workspace-divider" data-node-id="14:7502" />

          <div className="workspace-region-group">
            <p className="workspace-region-group__label">REGION A</p>
            <div className="workspace-aoi-card workspace-aoi-card--a" data-node-id="14:7504">
              <p className="workspace-aoi-card__overline">REGION</p>
              <p className="workspace-aoi-card__name">Caatinga · Brazil</p>
              <p className="workspace-aoi-card__meta">48,900 km² · Custom AOI</p>
              <p className="workspace-aoi-card__coords">8.5°S  39.5°W</p>
            </div>
          </div>

          <div className="workspace-region-group">
            <p className="workspace-region-group__label">REGION B</p>
            <div className="workspace-aoi-card workspace-aoi-card--b" data-node-id="14:7506">
              <p className="workspace-aoi-card__overline workspace-aoi-card__overline--b">
                REGION
              </p>
              <p className="workspace-aoi-card__name">Cerrado · Brazil</p>
              <p className="workspace-aoi-card__meta">47,600 km² · Custom AOI</p>
              <p className="workspace-aoi-card__coords">15.5°S  47.5°W</p>
            </div>
          </div>

          <div className="workspace-field-box" data-node-id="14:7508">
            <span className="workspace-field-box__label">DATE RANGE</span>
            <span className="workspace-field-box__value">Jan 2020 — Dec 2025</span>
          </div>

          <div className="workspace-field-box" data-node-id="14:7509">
            <span className="workspace-field-box__label">STRESS EVENT</span>
            <span className="workspace-field-box__value">Drought · Jun–Nov 2023</span>
          </div>

          <p className="workspace-config-rail__note" data-node-id="14:7510">
            Baseline: 2010–2019 · Same calendar month
          </p>

          <hr className="workspace-divider" data-node-id="14:7520" />
          <div className="workspace-config-rail__footer">
            <p className="workspace-config-rail__overline" data-node-id="14:7521">
              INFERENCE
            </p>
            <p className="workspace-config-rail__note" data-node-id="14:7522">
              Seasonal Mann–Kendall + Sen’s slope
            </p>
            <p className="workspace-config-rail__note" data-node-id="14:7523">
              α = 0.05 · No causal attribution
            </p>
          </div>
        </aside>

        <section
          className="workspace-state-card"
          data-node-id="14:7556"
          aria-labelledby="comp-empty-heading"
        >
          <p className="workspace-state-card__eyebrow" data-node-id="14:7557">
            COMPARATIVE ANALYSIS / EMPTY
          </p>
          <div className="workspace-state-card__content">
            <h2
              id="comp-empty-heading"
              className="workspace-state-card__title"
              data-node-id="14:7558"
            >
              Choose two regions to begin
            </h2>
            <p className="workspace-state-card__description" data-node-id="14:7559">
              Define a geographic comparison to investigate drought response and recovery.
            </p>

            <ol className="workspace-steps-list">
              <li data-node-id="14:7560">
                <span className="workspace-steps-list__num">01</span>
                <span>Choose Region A</span>
              </li>
              <li data-node-id="14:7561">
                <span className="workspace-steps-list__num">02</span>
                <span>Choose Region B</span>
              </li>
              <li data-node-id="14:7562">
                <span className="workspace-steps-list__num">03</span>
                <span>Select an event, dates and observation layers</span>
              </li>
            </ol>

            <p className="workspace-state-card__subnote" data-node-id="14:7563">
              Start with the synthetic Caatinga–Cerrado comparison, or configure your own AOIs.
            </p>

            <div className="workspace-state-card__actions">
              <Link to={APP_ROUTES.assessments} className="terra-link-reset">
                <Button variant="primary">Use sample regions</Button>
              </Link>
              <Link to={APP_ROUTES.explore} className="terra-link-reset">
                <Button variant="secondary">Configure regions</Button>
              </Link>
            </div>

            <p className="workspace-state-card__status-note" data-node-id="14:7568">
              No observations loaded. Nothing will be inferred before two valid regions are selected.
            </p>
          </div>

          <p className="workspace-state-card__provenance" data-node-id="14:7569">
            SYNTHETIC DATA · TERRA-SYN-2026-01 · Not for operational ecosystem-risk decisions
          </p>
        </section>
      </div>
    </div>
  )
}
