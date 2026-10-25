import { afterEach, describe, expect, it, vi } from 'vitest'

import { makeAccessToken } from '../../test/msw/handlers'
import {
  REFRESH_LEAD_MS,
  clearAccessToken,
  decodeJwtExp,
  getAccessToken,
  setAccessToken,
  setRefreshCallback,
} from './tokenStore'

const nowSeconds = () => Math.floor(Date.now() / 1000)

/** Zegar z zerową częścią milisekundową — inaczej `exp` (sekundy) daje przesunięcie < 1 s. */
function useClockAtSeconds(seconds: number): void {
  vi.useFakeTimers()
  vi.setSystemTime(seconds * 1000)
}

afterEach(() => {
  vi.useRealTimers()
  clearAccessToken()
  setRefreshCallback(null)
})

describe('decodeJwtExp', () => {
  it('zwraca exp z poprawnego tokenu, null dla złego', () => {
    expect(decodeJwtExp(makeAccessToken(1234))).toBe(1234)
    expect(decodeJwtExp('a.b.c')).toBeNull()
    expect(decodeJwtExp('bez-kropek')).toBeNull()
  })
})

describe('tokenStore', () => {
  it('trzyma token w pamięci modułu, poza localStorage i sessionStorage', () => {
    const token = makeAccessToken(nowSeconds() + 900)

    setAccessToken(token)

    expect(getAccessToken()).toBe(token)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('clearAccessToken czyści token i kasuje timer', () => {
    useClockAtSeconds(1_800_000_000)
    const cb = vi.fn(() => Promise.resolve(null))
    setRefreshCallback(cb)
    setAccessToken(makeAccessToken(nowSeconds() + 120))

    clearAccessToken()
    vi.advanceTimersByTime(REFRESH_LEAD_MS * 10)

    expect(getAccessToken()).toBeNull()
    expect(cb).not.toHaveBeenCalled()
  })

  it('woła callback dokładnie w REFRESH_LEAD_MS przed wygaśnięciem, nie wcześniej', () => {
    useClockAtSeconds(1_800_000_000)
    const cb = vi.fn(() => Promise.resolve(null))
    setRefreshCallback(cb)

    setAccessToken(makeAccessToken(nowSeconds() + 120))
    vi.advanceTimersByTime(REFRESH_LEAD_MS - 1)
    expect(cb).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('nowy token kasuje poprzedni timer', () => {
    useClockAtSeconds(1_800_000_000)
    const cb = vi.fn(() => Promise.resolve(null))
    setRefreshCallback(cb)

    setAccessToken(makeAccessToken(nowSeconds() + 120))
    setAccessToken(makeAccessToken(nowSeconds() + 300))
    vi.advanceTimersByTime(REFRESH_LEAD_MS)

    expect(cb).not.toHaveBeenCalled()

    vi.advanceTimersByTime(180_000)
    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('token bez poprawnego exp nie planuje timera', () => {
    useClockAtSeconds(1_800_000_000)
    const cb = vi.fn(() => Promise.resolve(null))
    setRefreshCallback(cb)

    setAccessToken('a.b.c')
    vi.advanceTimersByTime(REFRESH_LEAD_MS * 10)

    expect(decodeJwtExp('a.b.c')).toBeNull()
    expect(cb).not.toHaveBeenCalled()
    expect(getAccessToken()).toBe('a.b.c')
  })
})
