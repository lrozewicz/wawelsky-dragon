import { HttpResponse, http } from 'msw'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { clearAccessToken, getAccessToken, setAccessToken } from '../features/auth/tokenStore'
import { i18n, initI18n } from '../i18n'
import { apiUrl, fixtureUser, makeAccessToken } from '../test/msw/handlers'
import { server } from '../test/msw/server'
import { api, apiCall, refreshSession, setSessionExpiredHandler } from './client'

const nowSeconds = () => Math.floor(Date.now() / 1000)
const oldToken = () => makeAccessToken(nowSeconds() + 900)
const newToken = () => makeAccessToken(nowSeconds() + 1800)

const unauthorized = () => new HttpResponse(null, { status: 401 })

const refreshSuccess = (token: string) =>
  HttpResponse.json({ code: 0, message: 'success', data: { access_token: token, expires_in: 900 } })

beforeAll(async () => {
  await initI18n('pl')
})

afterEach(() => {
  clearAccessToken()
  setSessionExpiredHandler(null)
})

afterAll(() => {
  clearAccessToken()
})

describe('client — nagłówki', () => {
  it('dołącza Bearer z tokenem i Accept-Language', async () => {
    let authorization: string | null = null
    let acceptLanguage: string | null = null
    setAccessToken(oldToken())

    server.use(
      http.get(apiUrl('/api/v1/users/me'), ({ request }) => {
        authorization = request.headers.get('Authorization')
        acceptLanguage = request.headers.get('Accept-Language')
        return HttpResponse.json({ code: 0, message: 'success', data: fixtureUser })
      }),
    )

    const user = await apiCall<typeof fixtureUser>(api.GET('/api/v1/users/me'))

    expect(user).toEqual(fixtureUser)
    expect(authorization).toBe(`Bearer ${getAccessToken()}`)
    expect(acceptLanguage).toBe(i18n.language)
    expect(acceptLanguage).toBe('pl')
  })

  it('bez tokenu nie dodaje nagłówka Authorization', async () => {
    let authorization: string | null = 'nieustawione'
    server.use(
      http.get(apiUrl('/api/v1/users/me'), ({ request }) => {
        authorization = request.headers.get('Authorization')
        return HttpResponse.json({ code: 0, message: 'success', data: fixtureUser })
      }),
    )

    await api.GET('/api/v1/users/me')

    expect(authorization).toBeNull()
  })
})

describe('client — 401 i odświeżanie sesji', () => {
  it('trzy równoległe 401 dają dokładnie jedno odświeżenie i trzy sukcesy', async () => {
    const stale = oldToken()
    const fresh = newToken()
    let refreshCount = 0
    setAccessToken(stale)

    server.use(
      http.get(apiUrl('/api/v1/users/me'), ({ request }) =>
        request.headers.get('Authorization') === `Bearer ${stale}`
          ? unauthorized()
          : HttpResponse.json({ code: 0, message: 'success', data: fixtureUser }),
      ),
      http.post(apiUrl('/api/v1/auth/refresh'), () => {
        refreshCount += 1
        return refreshSuccess(fresh)
      }),
    )

    const results = await Promise.all([
      api.GET('/api/v1/users/me'),
      api.GET('/api/v1/users/me'),
      api.GET('/api/v1/users/me'),
    ])

    expect(refreshCount).toBe(1)
    expect(results.map((result) => result.response.status)).toEqual([200, 200, 200])
    expect(results[0]?.data).toEqual({ code: 0, message: 'success', data: fixtureUser })
    expect(getAccessToken()).toBe(fresh)
  })

  it('nieudane odświeżenie (401) woła sessionExpiredHandler i czyści token', async () => {
    const handler = vi.fn()
    setSessionExpiredHandler(handler)
    setAccessToken(oldToken())

    server.use(
      http.get(apiUrl('/api/v1/users/me'), unauthorized),
      http.post(apiUrl('/api/v1/auth/refresh'), unauthorized),
    )

    const result = await api.GET('/api/v1/users/me')

    expect(result.response.status).toBe(401)
    expect(handler).toHaveBeenCalledTimes(1)
    expect(getAccessToken()).toBeNull()
  })

  it('odświeżenie udane, ale powtórzone żądanie znów 401 → sessionExpiredHandler', async () => {
    const handler = vi.fn()
    setSessionExpiredHandler(handler)
    setAccessToken(oldToken())

    server.use(
      http.get(apiUrl('/api/v1/users/me'), unauthorized),
      http.post(apiUrl('/api/v1/auth/refresh'), () => refreshSuccess(newToken())),
    )

    const result = await api.GET('/api/v1/users/me')

    expect(result.response.status).toBe(401)
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('powtórzone po odświeżeniu żądanie POST niesie to samo ciało i nowe nagłówki', async () => {
    const stale = oldToken()
    const fresh = newToken()
    const bodies: string[] = []
    const authorizations: (string | null)[] = []
    const acceptLanguages: (string | null)[] = []
    setAccessToken(stale)

    server.use(
      http.patch(apiUrl('/api/v1/users/me'), async ({ request }) => {
        bodies.push(await request.text())
        authorizations.push(request.headers.get('Authorization'))
        acceptLanguages.push(request.headers.get('Accept-Language'))
        return bodies.length === 1
          ? unauthorized()
          : HttpResponse.json({ code: 0, message: 'success', data: fixtureUser })
      }),
      http.post(apiUrl('/api/v1/auth/refresh'), () => refreshSuccess(fresh)),
    )

    const body = {
      password: null,
      new_password: null,
      nickname: 'Nowy',
      avatar: null,
      language: null,
      timezone: null,
    }
    const result = await api.PATCH('/api/v1/users/me', { body })

    expect(result.response.status).toBe(200)
    expect(bodies).toHaveLength(2)
    expect(JSON.parse(bodies[1] ?? '')).toEqual(body)
    expect(authorizations).toEqual([`Bearer ${stale}`, `Bearer ${fresh}`])
    expect(acceptLanguages).toEqual(['pl', 'pl'])
    expect(getAccessToken()).toBe(fresh)
  })

  it('401 z /api/v1/auth/login nie uruchamia odświeżania', async () => {
    let refreshCount = 0
    setAccessToken(oldToken())

    server.use(
      http.post(apiUrl('/api/v1/auth/login'), unauthorized),
      http.post(apiUrl('/api/v1/auth/refresh'), () => {
        refreshCount += 1
        return refreshSuccess(newToken())
      }),
    )

    const result = await api.POST('/api/v1/auth/login', {
      body: { email: 'user@example.com', password: 'secret' },
    })

    expect(result.response.status).toBe(401)
    expect(refreshCount).toBe(0)
  })
})

describe('refreshSession', () => {
  it('odświeża i zapisuje nowy token', async () => {
    const fresh = newToken()
    setAccessToken(oldToken())
    server.use(http.post(apiUrl('/api/v1/auth/refresh'), () => refreshSuccess(fresh)))

    await expect(refreshSession()).resolves.toBe(fresh)
    expect(getAccessToken()).toBe(fresh)
  })

  it('nie wysyła Bearera na /auth/refresh', async () => {
    let authorization: string | null = 'nieustawione'
    setAccessToken(oldToken())
    server.use(
      http.post(apiUrl('/api/v1/auth/refresh'), ({ request }) => {
        authorization = request.headers.get('Authorization')
        return refreshSuccess(newToken())
      }),
    )

    await refreshSession()

    expect(authorization).toBeNull()
  })

  it('odpowiedź bez access_token → null i wyczyszczony token', async () => {
    setAccessToken(oldToken())
    server.use(
      http.post(apiUrl('/api/v1/auth/refresh'), () =>
        HttpResponse.json({ code: 0, message: 'success', data: false }),
      ),
    )

    await expect(refreshSession()).resolves.toBeNull()
    expect(getAccessToken()).toBeNull()
  })

  it('koperta code ≠ 0 → null i wyczyszczony token', async () => {
    setAccessToken(oldToken())
    server.use(
      http.post(apiUrl('/api/v1/auth/refresh'), () =>
        HttpResponse.json({ code: 403, message: 'nope', data: false }),
      ),
    )

    await expect(refreshSession()).resolves.toBeNull()
    expect(getAccessToken()).toBeNull()
  })

  it('błąd transportu → null i wyczyszczony token', async () => {
    setAccessToken(oldToken())
    server.use(http.post(apiUrl('/api/v1/auth/refresh'), () => HttpResponse.error()))

    await expect(refreshSession()).resolves.toBeNull()
    expect(getAccessToken()).toBeNull()
  })
})
