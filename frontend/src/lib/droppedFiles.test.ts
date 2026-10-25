import { describe, expect, it } from 'vitest'

import { formatNames, splitUnreadable, unreadableKey } from './droppedFiles'

describe('splitUnreadable', () => {
  it('pusta lista daje dwa puste wyniki', () => {
    expect(splitUnreadable([])).toEqual({ accepted: [], unreadable: [] })
  })

  it('plik 0 B trafia do unreadable (nazwa), reszta do accepted', () => {
    const empty = new File([], 'raport.pdf')
    expect(splitUnreadable([empty])).toEqual({ accepted: [], unreadable: ['raport.pdf'] })
  })

  it('mieszanka zachowuje kolejność wejściową w obu grupach', () => {
    const a = new File(['a'], 'a.pdf')
    const emptyOne = new File([], 'pusty1.pdf')
    const b = new File(['b'], 'b.pdf')
    const emptyTwo = new File([], 'pusty2.pdf')
    const split = splitUnreadable([a, emptyOne, b, emptyTwo])
    expect(split.accepted).toEqual([a, b])
    expect(split.unreadable).toEqual(['pusty1.pdf', 'pusty2.pdf'])
  })

  it('same pliki 0 B dają puste accepted', () => {
    const split = splitUnreadable([new File([], 'x.pdf'), new File([], 'y.pdf')])
    expect(split.accepted).toEqual([])
    expect(split.unreadable).toEqual(['x.pdf', 'y.pdf'])
  })
})

describe('unreadableKey', () => {
  it('mapuje źródło na klucz i18n z namespace common', () => {
    expect(unreadableKey('drop')).toBe('common.upload.unreadable.drop')
    expect(unreadableKey('pick')).toBe('common.upload.unreadable.pick')
  })
})

describe('formatNames', () => {
  it('łączy nazwy przecinkiem ze spacją', () => {
    expect(formatNames(['a', 'b'])).toBe('a, b')
  })

  it('pojedyncza nazwa bez separatora', () => {
    expect(formatNames(['raport.pdf'])).toBe('raport.pdf')
  })
})
