import { Link } from 'react-router'
import { Button } from './button'
import { StatusBadge } from './status-badge'

export interface PlaceholderSpecItem {
  label: string
  value: string
}

export interface PlaceholderMetricPreview {
  eyebrow: string
  value: string
  unit?: string
  caption: string
  tone?: 'default' | 'teal' | 'blue' | 'coral'
}

interface WorkspacePagePlaceholderProps {
  eyebrow: string
  title: string
  breadcrumb: string
  summary: string
  specifications: readonly PlaceholderSpecItem[]
  metrics?: readonly PlaceholderMetricPreview[]
  primaryActionLabel: string
  primaryActionTo: string
  secondaryActionLabel?: string
  secondaryActionTo?: string
  statusNote: string
}

export function WorkspacePagePlaceholder({
  eyebrow,
  title,
  breadcrumb,
  summary,
  specifications,
  metrics,
  primaryActionLabel,
  primaryActionTo,
  secondaryActionLabel = 'Return to Earth Observatory',
  secondaryActionTo = '/',
  statusNote,
}: WorkspacePagePlaceholderProps) {
  return (
    <div className="workspace-page">
      <section className="workspace-context-bar" aria-label="Analysis context">
        <div className="workspace-context-bar__titles">
          <h1 className="workspace-context-bar__heading">{title}</h1>
          <p className="workspace-context-bar__breadcrumb">{breadcrumb}</p>
        </div>
        <div className="workspace-context-bar__actions">
          <StatusBadge tone="synthetic">
            SYNTHETIC DATA · Research demonstration
          </StatusBadge>
          <Link to={primaryActionTo} className="terra-link-reset">
            <Button variant="primary">{primaryActionLabel}</Button>
          </Link>
        </div>
      </section>

      <div className="workspace-placeholder-shell">
        <aside className="workspace-config-rail" aria-label="Module specifications">
          <h2 className="workspace-config-rail__title">Module scope</h2>
          <p className="workspace-config-rail__subtitle">
            Architectural contract &amp; scientific parameters
          </p>
          <hr className="workspace-divider" />
          <dl className="workspace-spec-list">
            {specifications.map((spec) => (
              <div key={spec.label} className="workspace-spec-item">
                <dt className="workspace-spec-item__label">{spec.label}</dt>
                <dd className="workspace-spec-item__value">{spec.value}</dd>
              </div>
            ))}
          </dl>
          <hr className="workspace-divider" />
          <div className="workspace-config-rail__footer">
            <p className="workspace-config-rail__overline">PROVENANCE RULE</p>
            <p className="workspace-config-rail__note">
              Native grids retained · QC mask applied before aggregation · α = 0.05
            </p>
          </div>
        </aside>

        <section className="workspace-state-card" aria-labelledby="state-heading">
          <p className="workspace-state-card__eyebrow">{eyebrow}</p>
          <div className="workspace-state-card__content">
            <h2 id="state-heading" className="workspace-state-card__title">
              {title}
            </h2>
            <p className="workspace-state-card__description">{summary}</p>

            {metrics && metrics.length > 0 && (
              <div className="workspace-preview-grid">
                {metrics.map((metric) => (
                  <article key={metric.eyebrow} className="workspace-preview-card">
                    <p className="workspace-preview-card__eyebrow">{metric.eyebrow}</p>
                    <p
                      className={`workspace-preview-card__value ${
                        metric.tone ? `workspace-preview-card__value--${metric.tone}` : ''
                      }`.trim()}
                    >
                      {metric.value}
                      {metric.unit && (
                        <span className="workspace-preview-card__unit">{metric.unit}</span>
                      )}
                    </p>
                    <p className="workspace-preview-card__caption">{metric.caption}</p>
                  </article>
                ))}
              </div>
            )}

            <div className="workspace-state-card__actions">
              <Link to={primaryActionTo} className="terra-link-reset">
                <Button variant="primary">{primaryActionLabel}</Button>
              </Link>
              <Link to={secondaryActionTo} className="terra-link-reset">
                <Button variant="secondary">{secondaryActionLabel}</Button>
              </Link>
            </div>

            <p className="workspace-state-card__status-note">{statusNote}</p>
          </div>

          <p className="workspace-state-card__provenance">
            SYNTHETIC DATA · TERRA-SYN-2026-01 · Not for operational ecosystem-risk decisions
          </p>
        </section>
      </div>
    </div>
  )
}
