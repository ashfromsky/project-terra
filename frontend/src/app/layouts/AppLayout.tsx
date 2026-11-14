import { Suspense } from 'react'
import { Outlet } from 'react-router'
import { TopNavigation } from '../../widgets/top-navigation/TopNavigation'

function RouteLoadingFallback() {
  return (
    <div className="route-loading-fallback" role="status" aria-live="polite">
      <div className="route-loading-fallback__card">
        <p className="route-loading-fallback__eyebrow">TERRA WORKSPACE / LOADING</p>
        <p className="route-loading-fallback__title">Loading analytical view…</p>
        <div className="route-loading-fallback__track">
          <div className="route-loading-fallback__bar" />
        </div>
      </div>
    </div>
  )
}

export function AppLayout() {
  return (
    <div className="terra-app-layout">
      <TopNavigation />
      <main className="terra-app-main">
        <Suspense fallback={<RouteLoadingFallback />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  )
}
