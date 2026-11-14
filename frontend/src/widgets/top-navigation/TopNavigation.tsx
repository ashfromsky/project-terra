import { useState, useRef, useEffect } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router'
import { figmaAssets } from '../../shared/config/assets'
import { APP_ROUTES, WORKSPACE_NAV_ITEMS } from '../../shared/config/routes'
import { useUiStore } from '../../shared/store/ui-store'

export function TopNavigation() {
  const location = useLocation()
  const navigate = useNavigate()
  const isHomepage = location.pathname === APP_ROUTES.home

  const searchQuery = useUiStore((state) => state.searchQuery)
  const setSearchQuery = useUiStore((state) => state.setSearchQuery)
  const mobileNavOpen = useUiStore((state) => state.mobileNavOpen)
  const setMobileNavOpen = useUiStore((state) => state.setMobileNavOpen)

  const [workspacesMenuOpen, setWorkspacesMenuOpen] = useState(false)
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const workspacesRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        searchInputRef.current?.focus()
      }
      if (event.key === 'Escape') {
        setWorkspacesMenuOpen(false)
        setAccountMenuOpen(false)
        setMobileNavOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [setMobileNavOpen])

  useEffect(() => {
    function handleOutsideClick(event: MouseEvent) {
      if (
        workspacesRef.current &&
        !workspacesRef.current.contains(event.target as Node)
      ) {
        setWorkspacesMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [])

  if (isHomepage) {
    return (
      <header className="home-nav" data-node-id="5:111">
        <div className="home-nav__inner">
          <Link
            to={APP_ROUTES.home}
            className="home-nav__brand"
            aria-label="PROJECT TERRA Earth intelligence home"
          >
            <span className="home-nav__symbol-box" data-node-id="5:115">
              <span className="home-nav__symbol-frame" data-node-id="5:116">
                <img
                  src={figmaAssets.terraSymbol}
                  alt=""
                  className="home-nav__symbol-img"
                />
              </span>
            </span>
            <span className="home-nav__wordmark-group">
              <span className="home-nav__overline" data-node-id="5:122">
                PROJECT
              </span>
              <span className="home-nav__wordmark" data-node-id="5:121">
                TERRA
              </span>
            </span>
          </Link>

          <span className="home-nav__brand-dot" data-node-id="5:123" aria-hidden="true" />
          <span className="home-nav__tagline" data-node-id="5:124">
            Earth intelligence
          </span>

          <nav className="home-nav__links" aria-label="Primary navigation">
            <Link
              to={APP_ROUTES.explore}
              className="home-nav__link home-nav__link--active"
              data-node-id="5:125"
            >
              Explore
              <span
                className="home-nav__active-bar"
                data-node-id="5:126"
                aria-hidden="true"
              />
            </Link>

            <div className="home-nav__dropdown-wrapper" ref={workspacesRef}>
              <button
                type="button"
                className="home-nav__link home-nav__link-btn"
                data-node-id="5:127"
                aria-expanded={workspacesMenuOpen}
                aria-haspopup="menu"
                onClick={() => setWorkspacesMenuOpen((open) => !open)}
              >
                Workspaces
              </button>
              {workspacesMenuOpen && (
                <div className="home-nav__dropdown" role="menu" aria-label="TERRA routes">
                  {WORKSPACE_NAV_ITEMS.map((item) => (
                    <Link
                      key={item.path}
                      to={item.path}
                      role="menuitem"
                      className="home-nav__dropdown-item"
                      onClick={() => setWorkspacesMenuOpen(false)}
                    >
                      {item.label}
                    </Link>
                  ))}
                </div>
              )}
            </div>

            <Link
              to={APP_ROUTES.assessments}
              className="home-nav__link"
              data-node-id="5:128"
            >
              Methodology
            </Link>
          </nav>

          <form
            className="home-nav__search"
            data-node-id="5:129"
            role="search"
            onSubmit={(event) => {
              event.preventDefault()
              if (searchQuery.trim()) {
                navigate(
                  `${APP_ROUTES.explore}?q=${encodeURIComponent(searchQuery.trim())}`,
                )
              }
            }}
          >
            <img
              src={figmaAssets.search}
              alt=""
              className="home-nav__search-icon"
              data-node-id="5:130"
            />
            <input
              ref={searchInputRef}
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search datasets, places…"
              aria-label="Search datasets, places"
              className="home-nav__search-input"
              data-node-id="5:133"
            />
            <kbd className="home-nav__search-shortcut" data-node-id="5:134">
              <span data-node-id="5:135">⌘ K</span>
            </kbd>
          </form>

          <button
            type="button"
            className="home-nav__notifications"
            data-node-id="5:138"
            aria-label="Notifications"
            onClick={() => navigate(APP_ROUTES.reports)}
          >
            <img
              src={figmaAssets.notifications}
              alt=""
              className="home-nav__notifications-img"
            />
          </button>

          <div className="home-nav__account-wrap">
            <button
              type="button"
              className="home-nav__account"
              data-node-id="5:140"
              aria-label="Researcher account menu"
              aria-expanded={accountMenuOpen}
              onClick={() => setAccountMenuOpen((open) => !open)}
            >
              <img
                src={figmaAssets.researcherAccount}
                alt=""
                className="home-nav__account-avatar"
                data-node-id="5:141"
              />
              <img
                src={figmaAssets.openAccount}
                alt=""
                className="home-nav__account-chevron"
                data-node-id="5:144"
              />
            </button>
            {accountMenuOpen && (
              <div className="home-nav__dropdown home-nav__dropdown--right" role="menu">
                <div className="home-nav__dropdown-header">
                  <strong>Researcher</strong>
                  <span>NASA MODIS / IMERG Workspace</span>
                </div>
                {WORKSPACE_NAV_ITEMS.map((item) => (
                  <Link
                    key={item.path}
                    to={item.path}
                    role="menuitem"
                    className="home-nav__dropdown-item"
                    onClick={() => setAccountMenuOpen(false)}
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            )}
          </div>

          <button
            type="button"
            className="home-nav__mobile-trigger"
            aria-label="Toggle navigation menu"
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen(!mobileNavOpen)}
          >
            <img src={figmaAssets.mobileMenu} alt="" />
          </button>
        </div>

        {mobileNavOpen && (
          <nav className="mobile-nav-drawer" aria-label="Mobile navigation">
            <Link
              to={APP_ROUTES.home}
              className="mobile-nav-drawer__link mobile-nav-drawer__link--active"
              onClick={() => setMobileNavOpen(false)}
            >
              Earth Observatory (Home)
            </Link>
            {WORKSPACE_NAV_ITEMS.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                className="mobile-nav-drawer__link"
                onClick={() => setMobileNavOpen(false)}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        )}

        <div className="home-nav__divider" data-node-id="5:114" />
      </header>
    )
  }

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
          <Link
            to={APP_ROUTES.home}
            className="workspace-nav__account-pill"
            data-node-id="14:70"
            title="Return to Earth Observatory"
          >
            <span>Researcher  ⌄</span>
          </Link>
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
            className="mobile-nav-drawer__link"
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
