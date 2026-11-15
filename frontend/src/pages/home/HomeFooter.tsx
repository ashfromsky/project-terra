import { Link } from 'react-router'
import { brandAssets } from '../../shared/config/assets'
import { APP_ROUTES } from '../../shared/config/routes'
import { ExternalLink, Github } from '../../shared/ui/explorer-icons'

export function HomeFooter() {
  return (
    <footer className="terra-footer" aria-label="Project Terra footer">
      <div className="terra-footer__inner">
        <div className="terra-footer__brand-row">
          <Link to={APP_ROUTES.home} className="terra-footer__brand-link">
            <span className="terra-footer__brand-emblem">
              <img
                src={brandAssets.terraLogo}
                alt=""
                className="terra-footer__symbol"
              />
            </span>
            <span className="terra-footer__brand-text">
              <span className="terra-footer__brand-overline">PROJECT</span>
              <span className="terra-footer__brand-title">TERRA</span>
            </span>
          </Link>

          <p className="terra-footer__tagline">
            Planetary environmental monitoring and ecosystem resilience intelligence.
          </p>

          <a
            href="https://github.com/ashfromsky/project-terra"
            target="_blank"
            rel="noopener noreferrer"
            className="terra-footer__repo"
            aria-label="PROJECT TERRA repository on GitHub (opens in new tab)"
          >
            <Github size={15} aria-hidden="true" />
            <span>github.com/ashfromsky/project-terra</span>
            <ExternalLink size={12} aria-hidden="true" />
          </a>
        </div>

        <div className="terra-footer__links">
          <div className="terra-footer__col">
            <h3 className="terra-footer__col-title">Workspaces</h3>
            <ul className="terra-footer__list">
              <li>
                <Link to={APP_ROUTES.explore} className="terra-footer__link">
                  Live Map Explorer
                </Link>
              </li>
              <li>
                <Link to={APP_ROUTES.comparativeAnalysis} className="terra-footer__link">
                  Comparative Analysis
                </Link>
              </li>
              <li>
                <Link to={APP_ROUTES.assessments} className="terra-footer__link">
                  Scientific Assessments
                </Link>
              </li>
              <li>
                <Link to={APP_ROUTES.dataSources} className="terra-footer__link">
                  Data Sources &amp; Providers
                </Link>
              </li>
              <li>
                <Link to={APP_ROUTES.overview} className="terra-footer__link">
                  Platform Overview
                </Link>
              </li>
              <li>
                <Link to={APP_ROUTES.reports} className="terra-footer__link">
                  Reports &amp; Export
                </Link>
              </li>
            </ul>
          </div>

          <div className="terra-footer__col">
            <h3 className="terra-footer__col-title">Satellite feeds</h3>
            <ul className="terra-footer__list">
              <li>
                <Link
                  to={`${APP_ROUTES.explore}?gibs=MODIS_Terra_L3_NDVI_16Day`}
                  className="terra-footer__link"
                >
                  MODIS NDVI (vegetation)
                </Link>
              </li>
              <li>
                <Link
                  to={`${APP_ROUTES.explore}?gibs=MODIS_Terra_L3_EVI_16Day`}
                  className="terra-footer__link"
                >
                  MODIS EVI (enhanced)
                </Link>
              </li>
              <li>
                <Link
                  to={`${APP_ROUTES.explore}?gibs=MODIS_Terra_Land_Surface_Temp_Day`}
                  className="terra-footer__link"
                >
                  MODIS Land Surface Temp
                </Link>
              </li>
              <li>
                <Link
                  to={`${APP_ROUTES.explore}?gibs=IMERG_Precipitation_Rate`}
                  className="terra-footer__link"
                >
                  GPM IMERG precipitation
                </Link>
              </li>
              <li>
                <Link
                  to={`${APP_ROUTES.explore}?gibs=SMAP_L4_Analyzed_Surface_Soil_Moisture`}
                  className="terra-footer__link"
                >
                  SMAP soil moisture
                </Link>
              </li>
              <li>
                <Link
                  to={`${APP_ROUTES.explore}?gibs=MODIS_Terra_NDSI_Snow_Cover`}
                  className="terra-footer__link"
                >
                  MODIS NDSI snow cover
                </Link>
              </li>
            </ul>
          </div>

          <div className="terra-footer__col">
            <h3 className="terra-footer__col-title">Open science</h3>
            <ul className="terra-footer__list">
              <li>
                <a
                  href="https://gibs.earthdata.nasa.gov"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="terra-footer__link terra-footer__link--external"
                >
                  NASA EOSDIS GIBS
                  <ExternalLink size={11} aria-hidden="true" />
                </a>
              </li>
              <li>
                <a
                  href="https://power.larc.nasa.gov"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="terra-footer__link terra-footer__link--external"
                >
                  NASA POWER API
                  <ExternalLink size={11} aria-hidden="true" />
                </a>
              </li>
              <li>
                <a
                  href="https://planetarycomputer.microsoft.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="terra-footer__link terra-footer__link--external"
                >
                  Planetary Computer STAC
                  <ExternalLink size={11} aria-hidden="true" />
                </a>
              </li>
              <li>
                <a
                  href="https://openfreemap.org"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="terra-footer__link terra-footer__link--external"
                >
                  OpenFreeMap cartography
                  <ExternalLink size={11} aria-hidden="true" />
                </a>
              </li>
              <li>
                <a
                  href="https://www.spaceappschallenge.org"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="terra-footer__link terra-footer__link--external"
                >
                  Space Apps Challenge 2026
                  <ExternalLink size={11} aria-hidden="true" />
                </a>
              </li>
            </ul>
          </div>
        </div>

        <div className="terra-footer__bottom">
          <p>
            © 2026 PROJECT TERRA Contributors. Independent open-source research
            demonstration under MIT / Apache-2.0.
          </p>
          <p>
            Built at NASA Space Apps Challenge 2026. Not an official NASA website,
            service, or publication. Correlation does not establish causation (α = 0.05).
          </p>
        </div>
      </div>
    </footer>
  )
}
