import { describe, expect, it } from 'vitest'

import { canDelete, hasChunks, parsingState, progressPercent } from './parsingState'

describe('parsingState', () => {
  it('mapuje kod run na stan (SCHEDULE kolejka, RUNNING, DONE, FAIL, CANCEL)', () => {
    expect(parsingState({ run: 'SCHEDULE', progress: 0, chunk_count: 0 })).toBe('queued')
    expect(parsingState({ run: 'RUNNING', progress: 0.3, chunk_count: 0 })).toBe('running')
    expect(parsingState({ run: 'DONE', progress: 1, chunk_count: 4 })).toBe('done')
    expect(parsingState({ run: 'FAIL', progress: 0, chunk_count: 0 })).toBe('failed')
    expect(parsingState({ run: 'CANCEL', progress: 0, chunk_count: 0 })).toBe('cancelled')
  })

  it('UNSTART to spoczynek, ale z postępem w (0,1) już parsowanie', () => {
    expect(parsingState({ run: 'UNSTART', progress: 0, chunk_count: 0 })).toBe('idle')
    expect(parsingState({ run: 'UNSTART', progress: 0.4, chunk_count: 0 })).toBe('running')
    expect(parsingState({ run: 'UNSTART', progress: 1, chunk_count: 0 })).toBe('idle')
  })
})

describe('progressPercent', () => {
  it('zaokrągla i obcina postęp do zakresu 0..100', () => {
    expect(progressPercent(0.456)).toBe(46)
    expect(progressPercent(1.7)).toBe(100)
    expect(progressPercent(-1)).toBe(0)
    expect(progressPercent(0)).toBe(0)
    expect(progressPercent(0.5)).toBe(50)
    expect(progressPercent(1)).toBe(100)
  })
})

describe('canDelete', () => {
  it('blokuje usuwanie w trakcie parsowania i w kolejce, pozwala w spoczynku', () => {
    expect(canDelete({ run: 'RUNNING', progress: 0.2, chunk_count: 0 })).toBe(false)
    expect(canDelete({ run: 'SCHEDULE', progress: 0, chunk_count: 0 })).toBe(false)
    expect(canDelete({ run: 'UNSTART', progress: 0, chunk_count: 0 })).toBe(true)
    expect(canDelete({ run: 'DONE', progress: 1, chunk_count: 4 })).toBe(true)
  })
})

describe('hasChunks', () => {
  it('rozstrzyga po liczbie chunków', () => {
    expect(hasChunks({ chunk_count: 0 })).toBe(false)
    expect(hasChunks({ chunk_count: 3 })).toBe(true)
  })
})
