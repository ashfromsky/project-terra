import { Link } from 'react-router'
import { Button } from '../../shared/ui/button'
import { StatusBadge } from '../../shared/ui/status-badge'
import { APP_ROUTES } from '../../shared/config/routes'

interface ProductRow {
  layer: string
  product: string
  href: string
  version: string
  resolution: string
  gridTime: string
  qcFilter: string
  missingAB: string
  status: string
}

const NASA_PRODUCTS: readonly ProductRow[] = [
  {
    layer: 'NDVI / EVI',
    product: 'MOD13Q1 · LP DAAC',
    href: 'https://search.earthdata.nasa.gov/search?q=MOD13Q1',
    version: '6.1 / 061',
    resolution: '250 m · 16-day',
    gridTime: 'Native / Monthly',
    qcFilter: 'VI quality: good',
    missingAB: '4 / 2 months',
    status: 'Complete',
  },
  {
    layer: 'Land temperature',
    product: 'MOD11A2 · LP DAAC',
    href: 'https://doi.org/10.5067/MODIS/MOD11A2.061',
    version: '6.1 / 061',
    resolution: '1 km · 8-day',
    gridTime: 'Native / Monthly',
    qcFilter: 'LST error ≤ 1 K',
    missingAB: '6 / 4 months',
    status: 'Complete',
  },
  {
    layer: 'Land temperature (Global)',
    product: 'MOD11C3 · LP DAAC',
    href: 'https://search.earthdata.nasa.gov/search?q=MOD11C3',
    version: '6.1 / 061',
    resolution: '0.05° · Monthly',
    gridTime: 'CMG / Monthly',
    qcFilter: 'Daytime QC screened',
    missingAB: '300 / 300 valid',
    status: 'Complete',
  },
  {
    layer: 'Precipitation',
    product: 'IMERG Final · GES DISC',
    href: 'https://doi.org/10.5067/GPM/IMERG/3B-HH/07',
    version: 'V07',
    resolution: '0.1° · 30-min',
    gridTime: 'Native / Monthly sum',
    qcFilter: 'Final gauge-adjusted',
    missingAB: '0 / 0 months',
    status: 'Complete',
  },
]

export default function DataSourcesPage() {
  return (
    <div className="workspace-page">
      <section className="workspace-context-bar" aria-label="Data sources context">
        <div className="workspace-context-bar__titles">
          <h1 className="workspace-context-bar__heading">
            Data provenance &amp; quality
          </h1>
          <p className="workspace-context-bar__breadcrumb">
            Data Sources  /  NASA Earth Observation Catalog  /  Quality Screening
          </p>
        </div>
        <div className="workspace-context-bar__actions">
          <StatusBadge tone="synthetic">
            SYNTHETIC DATA · Research demonstration
          </StatusBadge>
          <Link to={APP_ROUTES.comparativeAnalysis} className="terra-link-reset">
            <Button variant="secondary">Comparative Analysis</Button>
          </Link>
          <Link to={APP_ROUTES.home} className="terra-link-reset">
            <Button variant="primary">Earth Observatory</Button>
          </Link>
        </div>
      </section>

      <div className="workspace-data-sources-shell">
        <section
          className="provenance-table-card"
          data-node-id="14:10"
          aria-labelledby="prov-heading"
        >
          <div className="provenance-table-card__header">
            <h2 id="prov-heading" className="provenance-table-card__title">
              Data provenance &amp; quality
            </h2>
            <p className="provenance-table-card__subtitle">
              Native grids retained · Area-weighted monthly aggregation · No gap-filling · Metadata reflects real NASA products; observations are synthetic.
            </p>
          </div>

          <div className="provenance-table-wrapper">
            <table className="provenance-table">
              <thead>
                <tr>
                  <th>LAYER</th>
                  <th>NASA PRODUCT ↗</th>
                  <th>VERSION</th>
                  <th>NATIVE RESOLUTION</th>
                  <th>ANALYSIS GRID / TIME</th>
                  <th>QUALITY FILTER</th>
                  <th>MISSING A / B</th>
                  <th>PROCESSING</th>
                </tr>
              </thead>
              <tbody>
                {NASA_PRODUCTS.map((row) => (
                  <tr key={row.product}>
                    <td className="provenance-table__primary">{row.layer}</td>
                    <td>
                      <a
                        href={row.href}
                        target="_blank"
                        rel="noreferrer"
                        className="provenance-table__link"
                      >
                        {row.product}
                      </a>
                    </td>
                    <td>{row.version}</td>
                    <td>{row.resolution}</td>
                    <td>{row.gridTime}</td>
                    <td>{row.qcFilter}</td>
                    <td>{row.missingAB}</td>
                    <td className="provenance-table__status">{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="provenance-table-card__footer">
            <p className="provenance-table-card__footnote">
              Snapshot TERRA-SYN-2026-01  ·  Baseline 2010–2019  ·  Observed window 2020–2025  ·  All numerical findings are illustrative.
            </p>
            <Link to={APP_ROUTES.assessments} className="provenance-table-card__link">
              Review TRI eligibility rules →
            </Link>
          </div>
        </section>
      </div>
    </div>
  )
}
