import { lazy } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { AppLayout } from './layouts/AppLayout'
import HomePage from '../pages/home/HomePage'

const OverviewPage = lazy(() => import('../pages/overview/OverviewPage'))
const ExplorePage = lazy(() => import('../pages/explore/ExplorePage'))
const ComparativeAnalysisPage = lazy(
  () => import('../pages/comparative-analysis/ComparativeAnalysisPage'),
)
const AssessmentsPage = lazy(
  () => import('../pages/assessments/AssessmentsPage'),
)
const ReportsPage = lazy(() => import('../pages/reports/ReportsPage'))
const DataSourcesPage = lazy(
  () => import('../pages/data-sources/DataSourcesPage'),
)
const NotFoundPage = lazy(() => import('../pages/not-found/NotFoundPage'))

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<HomePage />} />
          <Route path="overview" element={<OverviewPage />} />
          <Route path="explore" element={<ExplorePage />} />
          <Route
            path="comparative-analysis"
            element={<ComparativeAnalysisPage />}
          />
          <Route path="assessments" element={<AssessmentsPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="data-sources" element={<DataSourcesPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
