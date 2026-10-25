/**
 * Stan sesji przeglądarki (08 §5.3): odtworzenie sesji po F5, logowanie, wylogowanie
 * i role. Access token żyje wyłącznie w pamięci (`tokenStore`), a profil użytkownika
 * trafia do cache TanStack Query pod kluczem `['me']`.
 */

import type { QueryClient } from '@tanstack/react-query'

import { api, apiCall, refreshSession, setSessionExpiredHandler } from '../../api/client'
import type { components } from '../../api/schema.gen'
import { LANGUAGE_STORAGE_KEY, changeLanguage, i18n, resolveLanguage } from '../../i18n'
import { clearAccessToken, setAccessToken } from './tokenStore'

export type AuthUser = components['schemas']['User']

export type AuthState = {
  readonly user: AuthUser | null
  ensureSession(): Promise<AuthUser | null>
  login(email: string, password: string): Promise<AuthUser>
  /** Wylogowuje lokalnie; zwraca `logout_url` dostawcy tożsamości (konta OIDC) albo `null`. */
  logout(): Promise<string | null>
  hasRole(role: 'superuser'): boolean
}

type AuthStateDeps = {
  queryClient: QueryClient
  invalidate: () => Promise<void> | void
}

/** Klucz cache profilu bieżącego użytkownika (08 §9.2). */
const ME_QUERY_KEY = ['me']

export function createAuthState({ queryClient, invalidate }: AuthStateDeps): AuthState {
  let user: AuthUser | null = null
  // Jedno współdzielone odtworzenie sesji dla równoległych `ensureSession` (start aplikacji / guardy).
  let ensurePromise: Promise<AuthUser | null> | null = null

  // Wylogowanie lokalne: czyścimy token, profil, cache i unieważniamy router (08 §5.3).
  // Ekran logowania stosuje ostatni wybór z przeglądarki (K4/DEC-306), więc język sesji
  // (narzucony przez konto) ustępuje zapisowi `wd.language`. Zmiana tylko przy różnicy:
  // handler wygaśnięcia sesji może wołać localLogout przy każdym 401 w pętli, a każdy
  // `changeLanguage` (nawet ten sam język) wyzwala re-render całej aplikacji.
  async function localLogout(): Promise<void> {
    clearAccessToken()
    user = null
    queryClient.clear()
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY)
    if (stored !== null && resolveLanguage(i18n.language) !== resolveLanguage(stored)) {
      await changeLanguage(resolveLanguage(stored))
    } else if (stored === null && i18n.language) {
      // Brak wyboru przeglądarki: język konta zostaje na ekranie logowania także po F5 (SC-07 k6).
      localStorage.setItem(LANGUAGE_STORAGE_KEY, resolveLanguage(i18n.language))
    }
    await invalidate()
  }

  // Po ustaleniu profilu preferencja konta wygrywa w sesji (K4) i jest zapisywana do
  // `wd.language` (E67-z2 SC-19), by ekran logowania po wylogowaniu i F5 miał język konta;
  // puste `language` zostawia bieżący język (DEC-306).
  async function applyUser(next: AuthUser): Promise<AuthUser> {
    user = next
    queryClient.setQueryData(ME_QUERY_KEY, next)
    if (next.language !== '') await changeLanguage(resolveLanguage(next.language))
    return next
  }

  async function fetchMe(): Promise<AuthUser | null> {
    try {
      return await applyUser(await apiCall<AuthUser>(api.GET('/api/v1/users/me')))
    } catch {
      return null
    }
  }

  /** Odświeżenie cookie → pobranie profilu. Brak tokenu po refreshu kończy się bez żądania /me. */
  async function startSession(): Promise<AuthUser | null> {
    const token = await refreshSession()
    if (token === null) return null
    return fetchMe()
  }

  // Drugi 401 (po nieudanym refreshu/powtórzeniu) wygasza sesję lokalnie.
  setSessionExpiredHandler(() => void localLogout())

  return {
    get user(): AuthUser | null {
      return user
    },

    async ensureSession(): Promise<AuthUser | null> {
      if (user !== null) return user
      ensurePromise ??= startSession().finally(() => {
        ensurePromise = null
      })
      return ensurePromise
    },

    async login(email: string, password: string): Promise<AuthUser> {
      // Koperta loginu (RagflowOk[SessionUser]) nie deklaruje `access_token`, choć backend go
      // zwraca (08 §5.1) — stąd lokalne zawężenie typu odpowiedzi, bez zmiany kontraktu API.
      const data = await apiCall<AuthUser & { access_token: string }>(
        api.POST('/api/v1/auth/login', { body: { email, password } }),
      )
      setAccessToken(data.access_token)

      const me = await apiCall<AuthUser>(api.GET('/api/v1/users/me'))
      await applyUser(me)
      await invalidate()
      return me
    },

    async logout(): Promise<string | null> {
      let logoutUrl: string | null = null
      try {
        // `logout_url` (R10) leży obok `data` w kopercie, więc nie używamy tu `apiCall`.
        const { data } = await api.POST('/api/v1/auth/logout')
        const url = data?.logout_url
        if (typeof url === 'string' && url !== '') logoutUrl = url
      } catch {
        // Wylogowanie lokalne musi się udać nawet, gdy serwer zawiedzie.
      }
      await localLogout()
      return logoutUrl
    },

    hasRole(role: 'superuser'): boolean {
      return role === 'superuser' && user?.is_superuser === true
    },
  }
}
