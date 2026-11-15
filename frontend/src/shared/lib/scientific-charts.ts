import type { EChartsCoreOption } from 'echarts'

function shortDateLabel(timestamp: string): string {
  return timestamp.length >= 10 ? timestamp.slice(0, 10) : timestamp
}

export function buildTimeSeriesChartOption(params: {
  title: string
  variableName: string
  units?: string
  timestamps: string[]
  values: (number | null)[]
  color?: string
}): EChartsCoreOption {
  const labels = params.timestamps.map(shortDateLabel)
  const unitSuffix = params.units ? ` (${params.units})` : ''
  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
    },
    grid: {
      left: 56,
      right: 24,
      top: 38,
      bottom: 38,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#536e77', fontSize: 10 },
      axisLine: { lineStyle: { color: '#dce6e9' } },
    },
    yAxis: {
      type: 'value',
      name: `${params.variableName}${unitSuffix}`,
      nameTextStyle: { color: '#536e77', fontSize: 10 },
      axisLabel: { color: '#536e77', fontSize: 10 },
      splitLine: { lineStyle: { color: '#eef3f5' } },
    },
    series: [
      {
        name: params.variableName,
        type: 'line',
        data: params.values,
        smooth: false,
        showSymbol: labels.length <= 36,
        symbolSize: 5,
        connectNulls: false,
        lineStyle: { color: params.color ?? '#159b91', width: 2 },
        itemStyle: { color: params.color ?? '#159b91' },
      },
    ],
  }
}

export function buildAnomaliesChartOption(params: {
  variableName: string
  timestamps: string[]
  standardZscores: (number | null)[]
  robustZscores: (number | null)[]
}): EChartsCoreOption {
  const labels = params.timestamps.map(shortDateLabel)
  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
    },
    legend: {
      top: 4,
      right: 12,
      textStyle: { color: '#536e77', fontSize: 11 },
    },
    grid: {
      left: 56,
      right: 24,
      top: 40,
      bottom: 38,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#536e77', fontSize: 10 },
      axisLine: { lineStyle: { color: '#dce6e9' } },
    },
    yAxis: {
      type: 'value',
      name: `${params.variableName} Z-score (σ)`,
      nameTextStyle: { color: '#536e77', fontSize: 10 },
      axisLabel: { color: '#536e77', fontSize: 10 },
      splitLine: { lineStyle: { color: '#eef3f5' } },
    },
    series: [
      {
        name: 'Standard Z-score',
        type: 'bar',
        data: params.standardZscores,
        itemStyle: {
          color: (datum: { data?: unknown }) => {
            const val = typeof datum.data === 'number' ? datum.data : 0
            return val <= -1.5 ? '#c77f6d' : val >= 1.5 ? '#3193ce' : '#159b91'
          },
        },
      },
      {
        name: 'Robust Z-score (MAD)',
        type: 'line',
        data: params.robustZscores,
        showSymbol: false,
        lineStyle: { color: '#192f3a', width: 1.5, type: 'dashed' },
        itemStyle: { color: '#192f3a' },
      },
    ],
  }
}

export function buildComparisonOverlayChartOption(params: {
  variableName: string
  units?: string
  primaryLabel: string
  comparisonLabel: string
  primaryTimestamps: string[]
  primaryValues: (number | null)[]
  comparisonTimestamps: string[]
  comparisonValues: (number | null)[]
}): EChartsCoreOption {
  const unionDates = Array.from(
    new Set([
      ...params.primaryTimestamps.map(shortDateLabel),
      ...params.comparisonTimestamps.map(shortDateLabel),
    ]),
  ).sort()

  const pMap = new Map<string, number | null>()
  params.primaryTimestamps.forEach((ts, idx) => {
    pMap.set(shortDateLabel(ts), params.primaryValues[idx] ?? null)
  })
  const cMap = new Map<string, number | null>()
  params.comparisonTimestamps.forEach((ts, idx) => {
    cMap.set(shortDateLabel(ts), params.comparisonValues[idx] ?? null)
  })

  const unitSuffix = params.units ? ` (${params.units})` : ''
  return {
    animation: false,
    tooltip: { trigger: 'axis' },
    legend: {
      type: 'scroll',
      top: 4,
      left: 12,
      right: 12,
      textStyle: { color: '#536e77', fontSize: 11 },
    },
    grid: {
      left: 56,
      right: 24,
      top: 64,
      bottom: 38,
    },
    xAxis: {
      type: 'category',
      data: unionDates,
      axisLabel: { color: '#536e77', fontSize: 10 },
      axisLine: { lineStyle: { color: '#dce6e9' } },
    },
    yAxis: {
      type: 'value',
      name: `${params.variableName}${unitSuffix}`,
      nameLocation: 'end',
      nameGap: 14,
      nameTextStyle: { color: '#536e77', fontSize: 10, align: 'left' },
      axisLabel: { color: '#536e77', fontSize: 10 },
      splitLine: { lineStyle: { color: '#eef3f5' } },
    },
    series: [
      {
        name: params.primaryLabel,
        type: 'line',
        data: unionDates.map((d) => pMap.get(d) ?? null),
        connectNulls: true,
        showSymbol: unionDates.length <= 36,
        lineStyle: { color: '#159b91', width: 2 },
        itemStyle: { color: '#159b91' },
      },
      {
        name: params.comparisonLabel,
        type: 'line',
        data: unionDates.map((d) => cMap.get(d) ?? null),
        connectNulls: true,
        showSymbol: unionDates.length <= 36,
        lineStyle: { color: '#3193ce', width: 2 },
        itemStyle: { color: '#3193ce' },
      },
    ],
  }
}

export function buildHistogramChartOption(params: {
  bins: number[]
  counts: number[]
  variableName: string
  units?: string
  color?: string
}): EChartsCoreOption {
  const labels = params.bins.map((b) => b.toFixed(2))
  const unitSuffix = params.units ? ` (${params.units})` : ''
  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
    },
    grid: {
      left: 48,
      right: 16,
      top: 24,
      bottom: 28,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#536e77', fontSize: 9, interval: 2 },
      axisLine: { lineStyle: { color: '#dce6e9' } },
    },
    yAxis: {
      type: 'value',
      name: 'Pixels',
      nameTextStyle: { color: '#536e77', fontSize: 9 },
      axisLabel: { color: '#536e77', fontSize: 9 },
      splitLine: { lineStyle: { color: '#eef3f5' } },
    },
    series: [
      {
        name: `${params.variableName}${unitSuffix}`,
        type: 'bar',
        data: params.counts,
        barWidth: '85%',
        itemStyle: { color: params.color ?? '#159b91' },
      },
    ],
  }
}

export function buildMonthlyAnomalyOption(params: {
  title: string
  variableName: string
  timestamps: string[]
  anomalies: (number | null)[]
}): EChartsCoreOption {
  const labels = params.timestamps.map(shortDateLabel)
  return {
    animation: false,
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 18, top: 28, bottom: 30 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#536e77', fontSize: 9, interval: 2 },
      axisLine: { lineStyle: { color: '#dce6e9' } },
    },
    yAxis: {
      type: 'value',
      name: 'z-score',
      nameTextStyle: { color: '#536e77', fontSize: 9 },
      axisLabel: { color: '#536e77', fontSize: 9 },
      splitLine: { lineStyle: { color: '#eef3f5' } },
    },
    series: [
      {
        name: `${params.variableName} anomaly`,
        type: 'bar',
        data: params.anomalies,
        barWidth: '80%',
        itemStyle: { color: '#3193ce' },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{ yAxis: 0 }],
          lineStyle: { color: '#91a3aa', type: 'dashed' },
          label: { show: false },
        },
      },
    ],
  }
}
