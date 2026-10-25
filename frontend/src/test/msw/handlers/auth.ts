import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import { apiUrl } from './common'

// Typ zgodny z `User` (components.schemas.User w backend/openapi.json).
// `src/api/schema.gen.ts` powstaje w T1, więc do tego czasu trzymamy lokalny odpowiednik
// o identycznych polach; po jego pojawieniu się fixture jest przypisywalny do `AuthUser`.
export type FixtureUser = {
  id: string
  email: string
  nickname: string
  avatar: string | null
  language: string
  color_schema: string
  timezone: string | null
  is_superuser: boolean
  is_active: string
  last_login_time: string | null
  create_time: number
  create_date: string
  update_time: number
  update_date: string
  login_channel: string
}

export const fixtureUser: FixtureUser = {
  id: 'u1',
  email: 'user@example.com',
  nickname: 'User',
  avatar: null,
  language: 'pl',
  color_schema: 'Bright',
  timezone: null,
  is_superuser: false,
  is_active: '1',
  last_login_time: null,
  create_time: 1735689600,
  create_date: '2025-01-01 00:00:00',
  update_time: 1735689600,
  update_date: '2025-01-01 00:00:00',
  login_channel: 'password',
}

export const ACCESS_TOKEN_TTL_SECONDS = 900

export const LOGIN_EMAIL = 'user@example.com'
export const LOGIN_PASSWORD = 'secret'

// base64url bez bibliotek: btoa + zamiana `+`/`/`/`=`.
function base64Url(value: unknown): string {
  return btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

// Token z nieważnym podpisem, ale poprawnym base64url payloadem `{sub, exp}` — wystarcza
// do testów `decodeJwtExp` (TTL) i nagłówka Authorization.
export function makeAccessToken(expInSeconds: number): string {
  return `${base64Url({ alg: 'none', typ: 'JWT' })}.${base64Url({ sub: fixtureUser.id, exp: expInSeconds })}.sig`
}

function freshAccessToken(): string {
  return makeAccessToken(Math.floor(Date.now() / 1000) + ACCESS_TOKEN_TTL_SECONDS)
}

// Odpowiednik `LoginChannel` z backend/openapi.json (GET /api/v1/auth/login/channels).
export type FixtureLoginChannel = {
  channel: string
  display_name: string
  icon: string
}

// Domyślnie brak skonfigurowanych kanałów OIDC — testy nadpisują handler, gdy kanał jest potrzebny.
export const fixtureLoginChannel: FixtureLoginChannel = {
  channel: 'keycloak',
  display_name: 'Keycloak',
  icon: 'keycloak',
}

// Odpowiednik `SystemConfig` (GET /api/v1/system/config): `registerEnabled` jako liczba 0/1.
export type FixtureSystemConfig = {
  registerEnabled: number
  disablePasswordLogin: boolean
}

// Wartości domyślne instancji bez rejestracji i z włączonym logowaniem hasłem (Settings backendu).
export const fixtureSystemConfig: FixtureSystemConfig = {
  registerEnabled: 0,
  disablePasswordLogin: false,
}

// Konta OIDC: backend dokłada `logout_url` obok `data` (R10). Testy nadpisują domyślny handler
// tym wariantem, gdy sprawdzają przejście przeglądarki na dostawcę tożsamości (T3).
export function logoutWithUrl(url: string): HttpHandler {
  return http.post(apiUrl('/api/v1/auth/logout'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: true, logout_url: url }),
  )
}

// Login, odświeżenie i wylogowanie, profil użytkownika, rejestracja, kanały OIDC i konfiguracja
// systemu — kolejność tras jak w dotychczasowej tablicy `handlers`.
export const authHandlers: HttpHandler[] = [
  http.post(apiUrl('/api/v1/auth/login'), async ({ request }) => {
    const body = (await request.json()) as { email?: unknown; password?: unknown }

    if (body.email !== LOGIN_EMAIL || body.password !== LOGIN_PASSWORD) {
      return HttpResponse.json({
        code: 109,
        message: 'email or password is incorrect',
        data: false,
      })
    }

    return HttpResponse.json({
      code: 0,
      message: 'success',
      data: { ...fixtureUser, access_token: freshAccessToken() },
    })
  }),

  http.post(apiUrl('/api/v1/auth/refresh'), () =>
    HttpResponse.json({
      code: 0,
      message: 'success',
      data: { access_token: freshAccessToken(), expires_in: ACCESS_TOKEN_TTL_SECONDS },
    }),
  ),

  http.post(apiUrl('/api/v1/auth/logout'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: true }),
  ),

  http.get(apiUrl('/api/v1/users/me'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: fixtureUser }),
  ),

  // Częściowa aktualizacja profilu (np. zapis języka z powłoki): backend scala tylko obecne klucze.
  http.patch(apiUrl('/api/v1/users/me'), async ({ request }) => {
    const body = (await request.json()) as Partial<FixtureUser>
    return HttpResponse.json({ code: 0, message: 'success', data: { ...fixtureUser, ...body } })
  }),

  // Rejestracja lokalna kończy się od razu sesją (backend users.py: users_register → session_response).
  // Uwaga: realna ścieżka OpenAPI to POST /api/v1/users (operationId `users_register`) — CONTRACT
  // WP E3-2 podaje `/api/v1/users/register`, czego backend nie wystawia (patrz raport T2).
  http.post(apiUrl('/api/v1/users'), async ({ request }) => {
    const body = (await request.json()) as { nickname?: string; email?: string }
    return HttpResponse.json({
      code: 0,
      message: 'success',
      data: {
        ...fixtureUser,
        nickname: body.nickname ?? fixtureUser.nickname,
        email: body.email ?? fixtureUser.email,
        access_token: freshAccessToken(),
      },
    })
  }),

  http.get(apiUrl('/api/v1/auth/login/channels'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: [] }),
  ),

  http.get(apiUrl('/api/v1/system/config'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: fixtureSystemConfig }),
  ),
]
