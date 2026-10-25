import { describe, expect, it } from 'vitest'

import { safeRedirect } from './redirect'

describe('safeRedirect', () => {
  it('przepuszcza ścieżkę wewnętrzną z zapytaniem', () => {
    expect(safeRedirect('/datasets?x=1')).toBe('/datasets?x=1')
  })

  it('przepuszcza korzeń i ścieżkę zagnieżdżoną', () => {
    expect(safeRedirect('/')).toBe('/')
    expect(safeRedirect('/chat')).toBe('/chat')
  })

  // Wejście → wyjście dosłownie z tabeli wymagań briefu (T2).
  it.each([
    ['//evil.com', '/'],
    ['https://evil.com', '/'],
    [undefined, '/'],
    ['/\\evil', '/'],
  ])('sprowadza %s do %s', (value, expected) => {
    expect(safeRedirect(value)).toBe(expected)
  })

  it('odrzuca wartości spoza typu string', () => {
    expect(safeRedirect(null)).toBe('/')
    expect(safeRedirect(42)).toBe('/')
    expect(safeRedirect({ redirect: '/chat' })).toBe('/')
  })

  it('odrzuca ścieżkę bez wiodącego ukośnika', () => {
    expect(safeRedirect('chat')).toBe('/')
  })
})
