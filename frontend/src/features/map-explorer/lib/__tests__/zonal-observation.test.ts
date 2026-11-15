import { describe, expect, it } from 'vitest'
import { resolveZonalObservation } from '../zonal-observation'

const ndviLayer = {
  availableDates: ['2024-05-24'],
  activeDatasetId: 'f6fdc9f6-bb4a-4c17-a723-51e760563130',
}

describe('resolveZonalObservation', () => {
  it('uses the latest ingested observation when the requested date is unavailable', () => {
    expect(resolveZonalObservation(ndviLayer, '2025-12-01')).toEqual({
      date: '2024-05-24',
      displayDate: '2024-05-24',
      dateWasAdjusted: true,
      hasIngestedDataset: true,
    })
  })

  it('keeps the requested date when it is part of the ingested record', () => {
    expect(resolveZonalObservation(ndviLayer, '2024-05-24')).toEqual({
      date: '2024-05-24',
      displayDate: '2024-05-24',
      dateWasAdjusted: false,
      hasIngestedDataset: true,
    })
  })

  it('does not invent a date when the catalog exposes no ingested dates', () => {
    expect(
      resolveZonalObservation({ availableDates: [], activeDatasetId: 'ds-1' }, '2025-12-01'),
    ).toEqual({
      date: undefined,
      displayDate: '2025-12-01',
      dateWasAdjusted: false,
      hasIngestedDataset: true,
    })
  })

  it('marks layers without an ingested dataset as unavailable', () => {
    expect(
      resolveZonalObservation(
        { availableDates: [], activeDatasetId: null },
        '2025-12-01',
      ),
    ).toEqual({
      date: undefined,
      displayDate: '2025-12-01',
      dateWasAdjusted: false,
      hasIngestedDataset: false,
    })
  })

  it('handles a missing catalog layer without claiming an ingested dataset', () => {
    expect(resolveZonalObservation(null, '2025-12-01')).toEqual({
      date: undefined,
      displayDate: '2025-12-01',
      dateWasAdjusted: false,
      hasIngestedDataset: false,
    })
  })
})
