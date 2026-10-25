import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, fixtureModels, fixtureUser, makeAccessToken } from './handlers'

// Dekodowanie segmentu base64url JWT bez bibliotek (atob + dopełnienie do wielokrotności 4).
function decodePayload(token: string): { sub?: string; exp?: number } {
  const segment = token.split('.')[1] ?? ''
  const base64 = segment.replace(/-/g, '+').replace(/_/g, '/')
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
  return JSON.parse(atob(padded)) as { sub?: string; exp?: number }
}

const nowSeconds = () => Math.floor(Date.now() / 1000)

// Zamrożony zegar: `nowSeconds()` wołane dwa razy w jednym teście musi dać tę samą sekundę —
// bez tego test jest flakiem, gdy trafi w granicę sekundy (1735689600 = 2025-01-01 00:00:00 UTC).
const FROZEN_NOW_MS = 1_735_689_600_000

describe('handlery MSW — auth i users', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('apiUrl składa adres z origin', () => {
    expect(apiUrl('/api/v1/users/me')).toBe(window.location.origin + '/api/v1/users/me')
  })

  it('makeAccessToken daje trzy segmenty z poprawnym base64url payloadem', () => {
    vi.useFakeTimers()
    vi.setSystemTime(FROZEN_NOW_MS)

    const token = makeAccessToken(nowSeconds() + 900)

    expect(token.split('.')).toHaveLength(3)
    expect(decodePayload(token)).toEqual({ sub: 'u1', exp: nowSeconds() + 900 })
  })

  it('login z poprawnymi danymi zwraca code 0 i access_token z ważnym exp', async () => {
    const response = await fetch(apiUrl('/api/v1/auth/login'), {
      method: 'POST',
      body: JSON.stringify({ email: 'user@example.com', password: 'secret' }),
    })

    expect(response.status).toBe(200)
    const body = (await response.json()) as {
      code: number
      data: { email: string; access_token: string }
    }
    expect(body.code).toBe(0)
    expect(typeof body.data.access_token).toBe('string')
    expect(decodePayload(body.data.access_token)).toEqual({
      sub: 'u1',
      exp: expect.any(Number),
    })
    expect(decodePayload(body.data.access_token).exp).toBeGreaterThan(nowSeconds())
    expect(body.data.email).toBe(fixtureUser.email)
  })

  it('login ze złym adresem zwraca code 109', async () => {
    const response = await fetch(apiUrl('/api/v1/auth/login'), {
      method: 'POST',
      body: JSON.stringify({ email: 'zly@example.com', password: 'secret' }),
    })

    expect(response.status).toBe(200)
    const body = (await response.json()) as { code: number }
    expect(body.code).toBe(109)
  })

  it('refresh zwraca code 0 z access_token i expires_in', async () => {
    const response = await fetch(apiUrl('/api/v1/auth/refresh'), { method: 'POST' })

    expect(response.status).toBe(200)
    const body = (await response.json()) as {
      code: number
      data: { access_token: string; expires_in: number }
    }
    expect(body.code).toBe(0)
    expect(body.data.expires_in).toBe(900)
    expect(decodePayload(body.data.access_token).exp).toBeGreaterThan(nowSeconds())
  })

  it('logout zwraca code 0 i data true', async () => {
    const response = await fetch(apiUrl('/api/v1/auth/logout'), { method: 'POST' })

    expect(response.status).toBe(200)
    const body = (await response.json()) as { code: number; data: boolean }
    expect(body.code).toBe(0)
    expect(body.data).toBe(true)
  })

  it('users/me zwraca code 0 i pełnego użytkownika', async () => {
    const response = await fetch(apiUrl('/api/v1/users/me'))

    expect(response.status).toBe(200)
    const body = (await response.json()) as { code: number; data: typeof fixtureUser }
    expect(body.code).toBe(0)
    expect(body.data).toEqual(fixtureUser)
    expect(body.data.is_superuser).toBe(false)
    expect(body.data.language).toBe('pl')
  })

  it('users/me PATCH scala ciało żądania z użytkownikiem', async () => {
    const response = await fetch(apiUrl('/api/v1/users/me'), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: 'en' }),
    })

    expect(response.status).toBe(200)
    const body = (await response.json()) as { code: number; data: typeof fixtureUser }
    expect(body.code).toBe(0)
    expect(body.data.language).toBe('en')
    expect(body.data.email).toBe(fixtureUser.email)
  })

  it('users/me/models zwraca code 0 i modele z niepustym llm_id oraz embd_id', async () => {
    const response = await fetch(apiUrl('/api/v1/users/me/models'))

    expect(response.status).toBe(200)
    const body = (await response.json()) as { code: number; data: typeof fixtureModels }
    expect(body.code).toBe(0)
    expect(body.data).toEqual(fixtureModels)
    expect(body.data.llm_id).not.toBe('')
    expect(body.data.embd_id).not.toBe('')
  })
})
