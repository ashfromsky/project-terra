import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getTodayUtcIso } from '../../../../shared/lib/date'
import { useExploreStore } from '../../model/use-explore-store'
import { TemporalLegendBar } from '../TemporalLegendBar'

describe('TemporalLegendBar', () => {
  afterEach(() => {
    vi.useRealTimers()
    const today = getTodayUtcIso()
    useExploreStore.setState({
      selectedDate: today,
      dateRangeStart: '2020-01-01',
      dateRangeEnd: today,
      gibsLayerId: null,
      gibsDate: today,
      bottomPanelOpen: true,
    })
  })

  it('renders the timeline slider positioned at the current day by default', () => {
    const today = getTodayUtcIso()
    useExploreStore.setState({
      selectedDate: today,
      dateRangeStart: '2020-01-01',
      dateRangeEnd: today,
      gibsLayerId: null,
      bottomPanelOpen: true,
    })

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <TemporalLegendBar />
      </QueryClientProvider>,
    )

    const sliderMatch = html.match(/<input[^>]*explorer-timeline-slider[^>]*>/)
    expect(sliderMatch).not.toBeNull()
    const tag = sliderMatch![0]
    const maxMatch = tag.match(/max="(\d+)"/)
    const valueMatch = tag.match(/value="(\d+)"/)
    expect(maxMatch).not.toBeNull()
    expect(valueMatch).not.toBeNull()
    expect(valueMatch![1]).toBe(maxMatch![1])
    expect(html).toContain(`Target date: <strong>${today}</strong>`)
  })
})
