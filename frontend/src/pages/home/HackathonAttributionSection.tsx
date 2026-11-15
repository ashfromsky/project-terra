import { ExternalLink, Github, Info } from '../../shared/ui/explorer-icons'

export function HackathonAttributionSection() {
  return (
    <section
      className="attribution-section"
      aria-labelledby="hackathon-attribution-title"
    >
      <div className="attribution-section__inner">
        <div className="attribution-section__main">
          <p className="attribution-section__kicker">
            <span className="section-mark" aria-hidden="true" />
            Origin
          </p>
          <h2 id="hackathon-attribution-title" className="attribution-section__title">
            Built during NASA Space Apps Challenge 2026
          </h2>
          <p className="attribution-section__text">
            PROJECT TERRA was conceived, architected, and developed during the NASA
            Space Apps Challenge 2026 global hackathon. The project is an independent
            community effort to make planetary observation intelligence easier to
            inspect, question, and reproduce.
          </p>

          <div className="attribution-section__notice" role="note">
            <Info size={18} aria-hidden="true" />
            <p>
              <strong>Non-Affiliation Notice:</strong> PROJECT TERRA is an independent
              community project developed in the context of the hackathon. It is not an
              official NASA product, service, or publication, and is neither certified
              nor endorsed by NASA. Satellite imagery, reanalysis data, and
              hydrometeorological products are accessed through open NASA EOSDIS, GIBS,
              and partner APIs under standard public data policies.
            </p>
          </div>
        </div>

        <aside className="attribution-section__repo" aria-label="Repository and data sources">
          <p className="attribution-section__repo-kicker">Repository</p>
          <a
            href="https://github.com/ashfromsky/project-terra"
            target="_blank"
            rel="noopener noreferrer"
            className="attribution-section__repo-link"
          >
            <span>ashfromsky / project-terra</span>
            <ExternalLink size={14} aria-hidden="true" />
          </a>
          <p className="attribution-section__repo-meta">
            React 19 · TypeScript · MapLibre · FastAPI · Python 3.12 · GHS
          </p>

          <dl className="attribution-section__facts">
            <div>
              <dt>Open data</dt>
              <dd>NASA GIBS · LP DAAC · GES DISC · NSIDC · NASA POWER</dd>
            </div>
            <div>
              <dt>Cartography</dt>
              <dd>OpenFreeMap vector tiles · Natural Earth 110m</dd>
            </div>
          </dl>

          <a
            href="https://github.com/ashfromsky/project-terra"
            target="_blank"
            rel="noopener noreferrer"
            className="attribution-section__github"
          >
            <Github size={16} aria-hidden="true" />
            View source on GitHub
          </a>
        </aside>
      </div>
    </section>
  )
}
