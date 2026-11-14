import { Link, useLocation } from 'react-router'
import { Button } from '../../shared/ui/button'
import { APP_ROUTES } from '../../shared/config/routes'

export default function NotFoundPage() {
  const location = useLocation()

  return (
    <div className="workspace-page">
      <div className="workspace-data-sources-shell">
        <section className="workspace-state-card" aria-labelledby="not-found-heading">
          <p className="workspace-state-card__eyebrow workspace-state-card__eyebrow--error">
            NAVIGATION / 404 ROUTE NOT FOUND
          </p>
          <div className="workspace-state-card__content">
            <h1 id="not-found-heading" className="workspace-state-card__title">
              Requested workspace route does not exist
            </h1>
            <p className="workspace-state-card__description">
              No TERRA view is registered at <code>{location.pathname}</code>. Verify the URL or return to an active analytical workspace.
            </p>

            <div className="workspace-state-card__actions">
              <Link to={APP_ROUTES.home} className="terra-link-reset">
                <Button variant="primary">Return to Earth Observatory</Button>
              </Link>
              <Link to={APP_ROUTES.comparativeAnalysis} className="terra-link-reset">
                <Button variant="secondary">Open Comparative Analysis</Button>
              </Link>
            </div>
          </div>

          <p className="workspace-state-card__provenance">
            PROJECT TERRA · Earth System Intelligence
          </p>
        </section>
      </div>
    </div>
  )
}
