import { useState, useRef, useEffect } from 'react'
import { Link, NavLink, useLocation } from 'react-router'
import { figmaAssets } from '../../shared/config/assets'
import { APP_ROUTES, WORKSPACE_NAV_ITEMS } from '../../shared/config/routes'
import { useUiStore } from '../../shared/store/ui-store'

export function TopNavigation() {
  const location = useLocation()
  const mobileNavOpen = useUiStore((state) => state.mobileNavOpen)
  const setMobileNavOpen = useUiStore((state) => state.setMobileNavOpen)
  const [accountMenuPath, setAccountMenuPath] = useState<string | null>(null)
  const accountMenuRef = useRef<HTMLDivElement>(null)
  const isHomeRoute = location.pathname === APP_ROUTES.home
  const accountMenuOpen = accountMenuPath === location.pathname

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setAccountMenuPath(null)
        setMobileNavOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [setMobileNavOpen])

  useEffect(() => {
    function handleOutsideClick(event: MouseEvent) {
      if (
        accountMenuRef.current &&
        !accountMenuRef.current.contains(event.target as Node)
      ) {
        setAccountMenuPath(null)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [])

  return (
    <header className="workspace-nav" data-node-id="14:3">
      <div className="workspace-nav__inner">
        <Link to={APP_ROUTES.home} className="workspace-nav__brand" aria-label="TERRA Home">
          <span className="workspace-nav__symbol-box" data-node-id="14:48">
            <span className="workspace-nav__symbol-frame" data-node-id="14:49">
              <img
                src={figmaAssets.terraSymbol}
                alt=""
                className="workspace-nav__symbol-img"
              />
            </span>
          </span>
          <span className="workspace-nav__wordmark" data-node-id="14:54">
            TERRA
          </span>
        </Link>

        <nav className="workspace-nav__links" aria-label="Workspace navigation">
          {WORKSPACE_NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `workspace-nav__link ${isActive ? 'workspace-nav__link--active' : ''}`.trim()
              }
            >
              {({ isActive }) => (
                <>
                  <span>{item.label}</span>
                  {isActive && (
                    <span className="workspace-nav__active-bar" aria-hidden="true" />
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="workspace-nav__right">
          <span className="workspace-nav__context-label" data-node-id="14:69">
            RESEARCH WORKSPACE
          </span>
          <div className="workspace-nav__account-wrap" ref={accountMenuRef}>
            <button
              type="button"
              className="workspace-nav__account-pill"
              data-node-id="14:70"
              aria-haspopup="menu"
              aria-expanded={accountMenuOpen}
              onClick={() =>
                setAccountMenuPath((prev) =>
                  prev === location.pathname ? null : location.pathname,
                )
              }
            >
              <span>Researcher</span>
              <img src={figmaAssets.openAccount} alt="" className="workspace-nav__account-chevron" />
            </button>
            {accountMenuOpen && (
              <div className="workspace-nav__dropdown" role="menu" aria-label="Workspace menu">
                <div className="workspace-nav__dropdown-header">
                  <strong>Researcher</strong>
                  <span>Open science prototype workspace</span>
                </div>
                <Link
                  to={APP_ROUTES.home}
                  className="workspace-nav__dropdown-item"
                  role="menuitem"
                  onClick={() => setAccountMenuPath(null)}
                >
                  Earth Observatory (Home)
                </Link>
                <Link
                  to={APP_ROUTES.explore}
                  className="workspace-nav__dropdown-item"
                  role="menuitem"
                  onClick={() => setAccountMenuPath(null)}
                >
                  Map Explorer
                </Link>
                <Link
                  to={APP_ROUTES.comparativeAnalysis}
                  className="workspace-nav__dropdown-item"
                  role="menuitem"
                  onClick={() => setAccountMenuPath(null)}
                >
                  Comparative Analysis
                </Link>
              </div>
            )}
          </div>
          <button
            type="button"
            className="workspace-nav__mobile-trigger"
            aria-label="Toggle navigation menu"
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen(!mobileNavOpen)}
          >
            <img src={figmaAssets.mobileMenu} alt="" />
          </button>
        </div>
      </div>

      {mobileNavOpen && (
        <nav className="mobile-nav-drawer" aria-label="Mobile navigation">
          <Link
            to={APP_ROUTES.home}
            className={`mobile-nav-drawer__link ${
              isHomeRoute ? 'mobile-nav-drawer__link--active' : ''
            }`.trim()}
            onClick={() => setMobileNavOpen(false)}
          >
            Earth Observatory (Home)
          </Link>
          {WORKSPACE_NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `mobile-nav-drawer__link ${
                  isActive ? 'mobile-nav-drawer__link--active' : ''
                }`.trim()
              }
              onClick={() => setMobileNavOpen(false)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      )}

      <div className="workspace-nav__divider" data-node-id="14:68" />
    </header>
  )
}
