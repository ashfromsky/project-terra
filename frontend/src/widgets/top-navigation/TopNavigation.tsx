import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useSearchParams } from 'react-router'
import {
  buildGitHubLoginUrl,
  useCurrentUserQuery,
  useDevSessionLoginMutation,
  useLogoutMutation,
} from '../../shared/api/auth'
import { useSystemInfoQuery } from '../../shared/api/system'
import { brandAssets, figmaAssets } from '../../shared/config/assets'
import { APP_ROUTES, WORKSPACE_NAV_ITEMS } from '../../shared/config/routes'
import { useUiStore } from '../../shared/store/ui-store'

function formatAuthError(code: string): string {
  if (code === 'access_denied') {
    return 'GitHub sign-in was cancelled. You can continue exploring layers or retry sign-in.'
  }
  if (code === 'oauth_exchange_failed') {
    return 'GitHub OAuth sign-in failed while exchanging authorization code. Please retry.'
  }
  return `Authentication error: ${code}`
}

export function TopNavigation() {
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const mobileNavOpen = useUiStore((state) => state.mobileNavOpen)
  const setMobileNavOpen = useUiStore((state) => state.setMobileNavOpen)
  const [accountMenuPath, setAccountMenuPath] = useState<string | null>(null)
  const accountMenuRef = useRef<HTMLDivElement>(null)
  const isHomeRoute = location.pathname === APP_ROUTES.home
  const accountMenuOpen = accountMenuPath === location.pathname

  const userQuery = useCurrentUserQuery()
  const systemInfoQuery = useSystemInfoQuery()
  const logoutMutation = useLogoutMutation()

  const user = userQuery.data ?? null
  const oauthConfigured = systemInfoQuery.data?.githubOauthConfigured ?? false
  const devAuthEnabled = systemInfoQuery.data?.devAuthEnabled ?? false
  const devLoginMutation = useDevSessionLoginMutation()

  const handleDevSignIn = () => {
    devLoginMutation.mutate(undefined, {
      onSuccess: () => {
        setAccountMenuPath(null)
        setMobileNavOpen(false)
      },
    })
  }
  const apiOffline = systemInfoQuery.isError || (userQuery.isError && !user)
  const authError = searchParams.get('authError')

  const cleanParams = new URLSearchParams(searchParams)
  cleanParams.delete('authError')
  const cleanSearch = cleanParams.toString()
  const returnToPath = `${location.pathname}${cleanSearch ? `?${cleanSearch}` : ''}`
  const githubLoginUrl = buildGitHubLoginUrl(returnToPath)

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

  const dismissAuthError = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('authError')
    setSearchParams(next, { replace: true })
  }

  const handleSignOut = () => {
    logoutMutation.mutate(undefined, {
      onSuccess: () => {
        setAccountMenuPath(null)
        setMobileNavOpen(false)
      },
    })
  }

  const pillLabel = user
    ? (user.displayName ?? `@${user.githubLogin}`)
    : userQuery.isPending
      ? 'Session…'
      : oauthConfigured
        ? 'Sign in'
        : 'Researcher'

  return (
    <header className="workspace-nav" data-node-id="14:3">
      <div className="workspace-nav__inner">
        <Link
          to={APP_ROUTES.home}
          className="workspace-nav__brand"
          aria-label="Project Terra home"
        >
          <span className="workspace-nav__brand-emblem">
            <svg
              className="workspace-nav__brand-orbit"
              viewBox="0 0 48 48"
              fill="none"
              aria-hidden="true"
            >
              <circle
                cx="24"
                cy="24"
                r="20.25"
                stroke="currentColor"
                strokeOpacity="0.28"
                strokeWidth="1.15"
                strokeDasharray="46 17.6"
                strokeDashoffset="10"
                strokeLinecap="round"
              />
            </svg>
            <img
              src={brandAssets.terraLogo}
              alt=""
              className="workspace-nav__symbol-img"
            />
          </span>
        </Link>
        <span className="workspace-nav__brand-divider" aria-hidden="true" />

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
              {user?.avatarUrl && (
                <img
                  src={user.avatarUrl}
                  alt=""
                  className="workspace-nav__account-avatar"
                />
              )}
              <span>{pillLabel}</span>
              <img src={figmaAssets.openAccount} alt="" className="workspace-nav__account-chevron" />
            </button>

            {accountMenuOpen && (
              <div className="workspace-nav__dropdown" role="menu" aria-label="Workspace menu">
                <div className="workspace-nav__dropdown-header">
                  {user ? (
                    <>
                      <strong>{user.displayName ?? user.githubLogin}</strong>
                      <span>@{user.githubLogin}{user.email ? ` · ${user.email}` : ''}</span>
                    </>
                  ) : apiOffline ? (
                    <>
                      <strong>Core API offline</strong>
                      <span>Start TERRA Core API to sign in and sync saved regions</span>
                    </>
                  ) : oauthConfigured ? (
                    <>
                      <strong>Anonymous session</strong>
                      <span>Sign in with GitHub to persist regions to your workspace</span>
                    </>
                  ) : (
                    <>
                      <strong>Researcher</strong>
                      <span>GitHub OAuth not configured on backend API</span>
                    </>
                  )}
                </div>

                {!user && oauthConfigured && !apiOffline && (
                  <a
                    href={githubLoginUrl}
                    className="workspace-nav__dropdown-cta"
                    role="menuitem"
                    onClick={() => setAccountMenuPath(null)}
                  >
                    Sign in with GitHub
                  </a>
                )}

                {!user && devAuthEnabled && !apiOffline && (
                  <button
                    type="button"
                    className="workspace-nav__dropdown-cta"
                    role="menuitem"
                    disabled={devLoginMutation.isPending}
                    onClick={handleDevSignIn}
                  >
                    {devLoginMutation.isPending ? 'Starting dev session…' : 'Start Dev Session'}
                  </button>
                )}

                {devLoginMutation.isError && (
                  <p className="workspace-nav__dropdown-error" role="alert">
                    Failed to start dev session.
                  </p>
                )}

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

                {user && (
                  <>
                    <div className="workspace-nav__dropdown-sep" role="separator" />
                    <button
                      type="button"
                      className="workspace-nav__dropdown-item workspace-nav__dropdown-btn"
                      role="menuitem"
                      disabled={logoutMutation.isPending}
                      onClick={handleSignOut}
                    >
                      {logoutMutation.isPending ? 'Signing out…' : 'Sign out'}
                    </button>
                  </>
                )}

                {logoutMutation.isError && (
                  <p className="workspace-nav__dropdown-error" role="alert">
                    Failed to sign out. Please retry.
                  </p>
                )}
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
          <div className="mobile-nav-drawer__auth">
            {user ? (
              <div className="mobile-nav-drawer__user-row">
                <span>Signed in as @{user.githubLogin}</span>
                <button
                  type="button"
                  className="mobile-nav-drawer__auth-btn"
                  disabled={logoutMutation.isPending}
                  onClick={handleSignOut}
                >
                  {logoutMutation.isPending ? 'Signing out…' : 'Sign out'}
                </button>
              </div>
            ) : !apiOffline && (oauthConfigured || devAuthEnabled) ? (
              <div className="mobile-nav-drawer__user-row">
                {oauthConfigured && (
                  <a
                    href={githubLoginUrl}
                    className="mobile-nav-drawer__auth-link"
                    onClick={() => setMobileNavOpen(false)}
                  >
                    Sign in with GitHub
                  </a>
                )}
                {devAuthEnabled && (
                  <button
                    type="button"
                    className="mobile-nav-drawer__auth-btn"
                    disabled={devLoginMutation.isPending}
                    onClick={handleDevSignIn}
                  >
                    {devLoginMutation.isPending ? 'Starting dev session…' : 'Start Dev Session'}
                  </button>
                )}
              </div>
            ) : (
              <span className="mobile-nav-drawer__auth-note">
                {apiOffline ? 'Core API offline' : 'GitHub OAuth not configured'}
              </span>
            )}
          </div>
        </nav>
      )}

      <div className="workspace-nav__divider" data-node-id="14:68" />

      {authError && (
        <div className="workspace-nav__auth-banner" role="alert">
          <span>{formatAuthError(authError)}</span>
          <button
            type="button"
            className="workspace-nav__auth-dismiss"
            onClick={dismissAuthError}
          >
            Dismiss
          </button>
        </div>
      )}
    </header>
  )
}
