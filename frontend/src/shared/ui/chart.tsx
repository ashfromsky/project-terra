import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { EChartsCoreOption } from 'echarts'

interface ChartProps {
  /** Full ECharts option object describing the chart to render. */
  option: EChartsCoreOption
  className?: string
  /** Replace the whole option instead of merging on updates. */
  notMerge?: boolean
}

type EChartsInstance = ReturnType<typeof echarts.init>

/**
 * Generic Apache ECharts wrapper.
 *
 * Receives its configuration through props and owns the chart lifecycle:
 * create on mount, `setOption` on prop changes, dispose on unmount, and
 * `resize()` when the container size changes.
 */
export function Chart({ option, className, notMerge = true }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsInstance | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = echarts.init(container)
    chartRef.current = chart

    const observer = new ResizeObserver(() => {
      chart.resize()
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    chartRef.current?.setOption(option, notMerge)
  }, [option, notMerge])

  return <div ref={containerRef} className={className} />
}
