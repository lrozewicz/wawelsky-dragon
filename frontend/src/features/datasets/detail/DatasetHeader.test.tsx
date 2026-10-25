import { describe, expect, it } from 'vitest'

import { datasetInitials } from './DatasetHeader'

describe('datasetInitials', () => {
  it('bierze pierwszą literę nazwy (jedna litera)', () => {
    expect(datasetInitials('Baza testowa')).toBe('B')
    expect(datasetInitials('  baza   wiedzy  ')).toBe('B')
    expect(datasetInitials('Alfa')).toBe('A')
  })

  it('pomija nawiasy i znaki specjalne; cyfra też jest inicjałem (SC-E67-z2-22)', () => {
    expect(datasetInitials('E67-GUS (import 2026-10-14)')).toBe('E')
    expect(datasetInitials('(import) Łódź')).toBe('I')
    expect(datasetInitials('--7 baza')).toBe('7')
  })

  it('dla samego odstępu albo samych znaków specjalnych daje zaślepkę', () => {
    expect(datasetInitials('   ')).toBe('?')
    expect(datasetInitials('()-')).toBe('?')
  })
})
