import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useSideMenuMini } from './useSideMenuMini'

beforeEach(() => {
  localStorage.clear()
})

afterEach(cleanup)

describe('useSideMenuMini', () => {
  it('domyślnie zwraca tryb pełny', () => {
    const { result } = renderHook(() => useSideMenuMini(false))
    expect(result.current.mini).toBe(false)
  })

  it('toggle przełącza tryb mini i zapisuje wybór', () => {
    const { result } = renderHook(() => useSideMenuMini(false))

    act(() => {
      result.current.toggle()
    })

    expect(result.current.mini).toBe(true)
    expect(localStorage.getItem('wd.sideMenu.mini')).toBe('1')
  })

  it('autoMini wymusza tryb mini niezależnie od zapisu', () => {
    localStorage.setItem('wd.sideMenu.mini', '0')
    const { result } = renderHook(() => useSideMenuMini(true))
    expect(result.current.mini).toBe(true)
  })
})
