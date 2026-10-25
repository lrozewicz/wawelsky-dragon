/**
 * Wzorzec < md (kontrakt WP E3-7 §C2): `actionsFirst` w trybie compact przenosi kolumnę akcji
 * na początek, nie mutuje wejścia; poza trybem compact zwraca wejście tą samą referencją.
 * `useCompactGrid` w jsdom (brak `matchMedia`) zwraca `false` — wersja desktop.
 */

import { createElement } from 'react'
import { renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import AppTheme from '../theme/AppTheme'

import { actionsFirst, useCompactGrid, useStickyColumns } from './gridCompact'

type Column = { field: string }

describe('actionsFirst', () => {
  it('w trybie compact przenosi akcje na początek i nie mutuje wejścia', () => {
    const columns: Column[] = [{ field: 'name' }, { field: 'size' }, { field: 'actions' }]
    const snapshot = [...columns]

    const result = actionsFirst(columns, true)

    expect(result.map((column) => column.field)).toEqual(['actions', 'name', 'size'])
    expect(result).not.toBe(columns)
    expect(columns).toEqual(snapshot)
  })

  it('poza trybem compact zwraca tę samą tablicę', () => {
    const columns: Column[] = [{ field: 'name' }, { field: 'actions' }]

    expect(actionsFirst(columns, false)).toBe(columns)
  })

  it('gdy nie ma kolumny akcji, w trybie compact zwraca wejście', () => {
    const columns: Column[] = [{ field: 'name' }, { field: 'size' }]

    expect(actionsFirst(columns, true)).toBe(columns)
  })
})

describe('useCompactGrid', () => {
  it('w jsdom bez matchMedia zwraca false (desktop)', () => {
    const { result } = renderHook(() => useCompactGrid(), {
      wrapper: ({ children }) => createElement(AppTheme, null, children),
    })

    expect(result.current).toBe(false)
  })
})

describe('useStickyColumns', () => {
  const SM_DOWN = '(max-width:599.95px)'
  const MD_DOWN = '(max-width:899.95px)'
  const originalMatchMedia = window.matchMedia
  const originalWidth = window.innerWidth

  afterEach(() => {
    window.matchMedia = originalMatchMedia
    Object.defineProperty(window, 'innerWidth', { value: originalWidth })
  })

  /** Wymusza wyniki zapytań mediów i szerokość okna (jsdom nie ma matchMedia ani układu). */
  function stubViewport(width: number, matches: string[]): void {
    window.matchMedia = ((query: string) =>
      ({
        matches: matches.includes(query),
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
      }) as unknown as MediaQueryList) as typeof window.matchMedia
    Object.defineProperty(window, 'innerWidth', { value: width, configurable: true })
  }

  function renderColumns(
    ...args: Parameters<typeof useStickyColumns>
  ): ReturnType<typeof useStickyColumns> {
    const { result } = renderHook(() => useStickyColumns(...args), {
      wrapper: ({ children }) => createElement(AppTheme, null, children),
    })
    return result.current
  }

  it('desktop: checkbox (gdy jest) i Nazwa, bez ⋮', () => {
    stubViewport(1280, [])
    expect(renderColumns('name', 190, { check: '__check__', actions: 'actions' })).toEqual([
      '__check__',
      'name',
    ])
  })

  it('kompakt (600–900 px): dołącza ⋮ przed Nazwą', () => {
    stubViewport(700, [MD_DOWN])
    expect(renderColumns('name', 190, { check: '__check__', actions: 'actions' })).toEqual([
      '__check__',
      'actions',
      'name',
    ])
  })

  it('wąski 390 px: tylko Nazwa — Nazwa+⋮ przekraczają ~45% okna, checkbox przewija się', () => {
    stubViewport(390, [SM_DOWN, MD_DOWN])
    // Nazwa 190 + ⋮ 64 = 254 px > 45% z 390 (175,5 px) — ⋮ nie mieści się w budżecie.
    expect(renderColumns('name', 190, { actions: 'actions' })).toEqual(['name'])
  })

  it('wąski 500 px z wąską kolumną nazwy: ⋮ dołącza (Nazwa+⋮ mieści się w 45%)', () => {
    stubViewport(500, [SM_DOWN, MD_DOWN])
    // Nazwa 120 + ⋮ 64 = 184 px <= 45% z 500 (225 px) — widoczny pas treści ~284 px.
    expect(renderColumns('name', 120, { actions: 'actions' })).toEqual(['actions', 'name'])
  })
})
