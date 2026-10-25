import { QueryClient } from '@tanstack/react-query'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, setSessionExpiredHandler } from '../../api/client'
import { ApiError } from '../../api/envelope'
import { i18n, initI18n } from '../../i18n'
import {
  LOGIN_EMAIL,
  LOGIN_PASSWORD,
  apiUrl,
  fixtureUser,
  logoutWithUrl,
  makeAccessToken,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { createAuthState } from './authState'
import { clearAccessToken, getAccessToken } from './tokenStore'

const unauthorized = () => new HttpResponse(null, { status: 401 })
const freshToken = () => makeAccessToken(Math.floor(Date.now() / 1000) + 900)
const refreshSuccess = () =>
  HttpResponse.json({
    code: 0,
    message: 'success',
    data: { access_token: freshToken(), expires_in: 900 },
  })

const invalidate = vi.fn()

function setupAuth() {
  const queryClient = new QueryClient()
  const auth = createAuthState({ queryClient, invalidate })
  return { auth, queryClient }
}

// Zwraca rzucony błąd (albo null), by dało się go zbadać bez `catch` w każdym teście.
async function rejection(promise: Promise<unknown>): Promise<unknown> {
  return promise.then(
    () => null,
    (reason: unknown) => reason,
  )
}

beforeEach(async () => {
  invalidate.mockReset()
  clearAccessToken()
  setSessionExpiredHandler(null)
  await initI18n('pl')
})

afterEach(() => {
  clearAccessToken()
  setSessionExpiredHandler(null)
})

describe('login', () => {
  it('poprawne dane ustawiają profil, token i unieważniają router', async () => {
    const { auth, queryClient } = setupAuth()

    const user = await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)

    expect(user.email).toBe(fixtureUser.email)
    expect(auth.user).toEqual(fixtureUser)
    expect(getAccessToken()).not.toBeNull()
    expect(invalidate).toHaveBeenCalledTimes(1)
    expect(queryClient.getQueryData(['me'])).toEqual(fixtureUser)
  })

  it('błędne dane rzucają ApiError 109 bez ustawiania sesji', async () => {
    const { auth } = setupAuth()

    const error = await rejection(auth.login(LOGIN_EMAIL, 'złe-hasło'))

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe(109)
    expect(auth.user).toBeNull()
    expect(getAccessToken()).toBeNull()
    expect(invalidate).not.toHaveBeenCalled()
  })

  it('język interfejsu podąża za profilem użytkownika', async () => {
    const { auth } = setupAuth()
    server.use(
      http.get(apiUrl('/api/v1/users/me'), () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: { ...fixtureUser, language: 'en' },
        }),
      ),
    )

    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)

    expect(i18n.language).toBe('en')
  })
})

describe('ensureSession', () => {
  it('po F5 odtwarza sesję z cookie (bez tokenu w pamięci)', async () => {
    const { auth } = setupAuth()
    expect(getAccessToken()).toBeNull()

    const user = await auth.ensureSession()

    expect(user).toEqual(fixtureUser)
    expect(auth.user).toEqual(fixtureUser)
    expect(getAccessToken()).not.toBeNull()
  })

  it('gdy refresh zwraca 401, zwraca null i nie ustawia sesji', async () => {
    const { auth } = setupAuth()
    server.use(http.post(apiUrl('/api/v1/auth/refresh'), unauthorized))

    await expect(auth.ensureSession()).resolves.toBeNull()
    expect(auth.user).toBeNull()
    expect(getAccessToken()).toBeNull()
  })

  it('zwraca już ustawiony profil bez odświeżania', async () => {
    const { auth } = setupAuth()
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)
    let refreshCount = 0
    server.use(
      http.post(apiUrl('/api/v1/auth/refresh'), () => {
        refreshCount += 1
        return refreshSuccess()
      }),
    )

    await expect(auth.ensureSession()).resolves.toEqual(fixtureUser)
    expect(refreshCount).toBe(0)
  })

  it('równoległe wywołania dzielą jedno odświeżenie', async () => {
    const { auth } = setupAuth()
    let refreshCount = 0
    server.use(
      http.post(apiUrl('/api/v1/auth/refresh'), () => {
        refreshCount += 1
        return refreshSuccess()
      }),
    )

    const results = await Promise.all([
      auth.ensureSession(),
      auth.ensureSession(),
      auth.ensureSession(),
    ])

    expect(refreshCount).toBe(1)
    expect(results).toEqual([fixtureUser, fixtureUser, fixtureUser])
  })
})

describe('logout', () => {
  it('czyści token, profil i cache oraz unieważnia router', async () => {
    const { auth, queryClient } = setupAuth()
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)
    expect(queryClient.getQueryCache().getAll().length).toBeGreaterThan(0)

    await auth.logout()

    expect(getAccessToken()).toBeNull()
    expect(auth.user).toBeNull()
    expect(queryClient.getQueryCache().getAll().length).toBe(0)
    expect(invalidate).toHaveBeenCalledTimes(2)
  })

  it('kończy się lokalnie także, gdy /auth/logout zwraca 500', async () => {
    const { auth, queryClient } = setupAuth()
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)
    server.use(
      http.post(apiUrl('/api/v1/auth/logout'), () => new HttpResponse(null, { status: 500 })),
    )

    expect(await auth.logout()).toBeNull()

    expect(getAccessToken()).toBeNull()
    expect(auth.user).toBeNull()
    expect(queryClient.getQueryCache().getAll().length).toBe(0)
  })

  it('zwraca logout_url dostawcy tożsamości dla konta OIDC', async () => {
    const { auth } = setupAuth()
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)
    server.use(logoutWithUrl('https://idp.example/logout'))

    expect(await auth.logout()).toBe('https://idp.example/logout')
  })

  it('zwraca null, gdy konto jest lokalne (brak logout_url)', async () => {
    const { auth } = setupAuth()
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)

    expect(await auth.logout()).toBeNull()
  })

  it('zwraca null i kończy lokalnie, gdy sieć zawodzi', async () => {
    const { auth } = setupAuth()
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)
    server.use(http.post(apiUrl('/api/v1/auth/logout'), () => HttpResponse.error()))

    expect(await auth.logout()).toBeNull()
    expect(auth.user).toBeNull()
  })
})

describe('hasRole', () => {
  it('odzwierciedla is_superuser profilu', async () => {
    const { auth } = setupAuth()
    expect(auth.hasRole('superuser')).toBe(false)

    server.use(
      http.get(apiUrl('/api/v1/users/me'), () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: { ...fixtureUser, is_superuser: true },
        }),
      ),
    )
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)

    expect(auth.hasRole('superuser')).toBe(true)
  })
})

describe('wygaszenie sesji', () => {
  it('drugi 401 w kliencie wygasza sesję lokalnie', async () => {
    const { auth, queryClient } = setupAuth()
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)
    expect(auth.user).not.toBeNull()

    server.use(
      http.get(apiUrl('/api/v1/users/me'), unauthorized),
      http.post(apiUrl('/api/v1/auth/refresh'), unauthorized),
    )

    await api.GET('/api/v1/users/me')

    expect(auth.user).toBeNull()
    expect(getAccessToken()).toBeNull()
    expect(queryClient.getQueryCache().getAll().length).toBe(0)
    expect(invalidate).toHaveBeenCalledTimes(2)
  })
})
