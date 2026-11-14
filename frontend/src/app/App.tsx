import { MapView } from '../shared/ui/map-view'
import { Chart } from '../shared/ui/chart'
import { useUiStore } from '../shared/store/ui-store'
import { useHealthQuery } from '../shared/api/health'

/**
 * Synthetic series used only to verify the chart wiring. Clearly labeled as an
 * illustrative dataset; replace with data fetched through TanStack Query once
 * the core API exposes real endpoints.
 */
const wiringDemoOption = {
  title: { text: 'Chart wiring demo (synthetic)', textStyle: { fontSize: 14 } },
  xAxis: { type: 'category', data: ['a', 'b', 'c', 'd'] },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: [2, 4, 1, 3] }],
}

export function App() {
  const panelOpen = useUiStore((state) => state.panelOpen)
  const togglePanel = useUiStore((state) => state.togglePanel)
  const healthQuery = useHealthQuery()

  return (
    <div className="app-shell">
      <MapView className="app-map" />
      {panelOpen && (
        <aside className="app-panel">
          <h1>TERRA</h1>
          <p className="app-status">
            API{' '}
            {healthQuery.isPending
              ? 'connecting…'
              : healthQuery.isError
                ? 'unreachable'
                : `online (${healthQuery.data.status})`}
          </p>
          <Chart option={wiringDemoOption} className="app-chart" />
        </aside>
      )}
      <button type="button" className="app-panel-toggle" onClick={togglePanel}>
        {panelOpen ? 'Hide panel' : 'Show panel'}
      </button>
    </div>
  )
}
