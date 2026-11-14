export const APP_ROUTES = {
  home: '/',
  overview: '/overview',
  explore: '/explore',
  comparativeAnalysis: '/comparative-analysis',
  assessments: '/assessments',
  reports: '/reports',
  dataSources: '/data-sources',
} as const

export interface NavItem {
  label: string
  path: string
}

export const WORKSPACE_NAV_ITEMS: readonly NavItem[] = [
  { label: 'Overview', path: APP_ROUTES.overview },
  { label: 'Explore', path: APP_ROUTES.explore },
  { label: 'Comparative Analysis', path: APP_ROUTES.comparativeAnalysis },
  { label: 'Assessments', path: APP_ROUTES.assessments },
  { label: 'Reports', path: APP_ROUTES.reports },
  { label: 'Data Sources', path: APP_ROUTES.dataSources },
] as const
