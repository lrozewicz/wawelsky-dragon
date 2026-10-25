/**
 * Trwały język interfejsu (DEC-306, wydzielone z `authState.test.ts` — limit 300 linii):
 * preferencja konta wygrywa w sesji, ale nie zapisuje się jako ostatni wybór przeglądarki;
 * po wylogowaniu ekran logowania wraca do zapisu `wd.language`.
 */

import { QueryClient } from '@tanstack/react-query'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setSessionExpiredHandler } from '../../api/client'
import { LANGUAGE_STORAGE_KEY, i18n, initI18n } from '../../i18n'
import { LOGIN_EMAIL, LOGIN_PASSWORD, apiUrl, fixtureUser } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { createAuthState } from './authState'
import { clearAccessToken } from './tokenStore'

const invalidate = vi.fn()

function setupAuth() {
  const queryClient = new QueryClient()
  const auth = createAuthState({ queryClient, invalidate })
  return { auth, queryClient }
}

/** GET /users/me z kontem o podanym języku (domoślnie atapia `fixtureUser`). */
function meWithLanguage(language: string): void {
  server.use(
    http.get(apiUrl('/api/v1/users/me'), () =>
      HttpResponse.json({
        code: 0,
        message: 'success',
        data: { ...fixtureUser, language },
      }),
    ),
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
  localStorage.removeItem(LANGUAGE_STORAGE_KEY)
})

describe('trwały język (DEC-306)', () => {
  it('preferencja konta jest stosowana i zapisywana do wd.language (SC-E67-z2-19)', async () => {
    const { auth } = setupAuth()
    meWithLanguage('en')

    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)

    // UI po angielsku (konto) i `wd.language` zgodny z kontem — ekran logowania po wylogowaniu
    // i F5 nie zostaje na starej wartości z przeglądarki ('pl' z initI18n w beforeEach).
    expect(i18n.language).toBe('en')
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('en')
  })

  it('puste language konta zostawia bieżący język UI', async () => {
    const { auth } = setupAuth()
    meWithLanguage('')

    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)

    expect(i18n.language).toBe('pl')
  })

  it('po wylogowaniu wraca do ostatniego wyboru języka z przeglądarki', async () => {
    const { auth } = setupAuth()
    meWithLanguage('en')
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)
    expect(i18n.language).toBe('en')
    // Ręczna zmiana wyboru przeglądarki w trakcie sesji (np. przełącznik na ekranie logowania).
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'pl')

    await auth.logout()

    // Ekran logowania stosuje ostatni wybór z `wd.language`, nie język konta.
    expect(i18n.language).toBe('pl')
  })

  it('po wylogowaniu bez zapisu wyboru zostawia język sesji', async () => {
    const { auth } = setupAuth()
    meWithLanguage('en')
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)
    localStorage.removeItem(LANGUAGE_STORAGE_KEY)

    await auth.logout()

    expect(i18n.language).toBe('en')
    // Język konta przeżywa odświeżenie ekranu logowania (QA-UI #1, SC-07 k6): zapisany jako wybór.
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('en')
  })

  it('wylogowanie woła changeLanguage tylko przy różnicy (pętla 401 jest bezpieczna, T5)', async () => {
    const { auth } = setupAuth()

    // Język sesji ('pl' z initI18n) zgodny z zapisem `wd.language`: zero przełączeń —
    // każdy changeLanguage (nawet ten sam język) re-renderuje całą aplikację, a handler
    // wygaśnięcia sesji może wołać localLogout przy każdym 401.
    const changeSpy = vi.spyOn(i18n, 'changeLanguage')
    await auth.logout()
    expect(changeSpy).not.toHaveBeenCalled()

    // Sesja na koncie EN, zapis 'pl': pierwszy localLogout wraca do 'pl' — dokładnie raz.
    meWithLanguage('en')
    await auth.login(LOGIN_EMAIL, LOGIN_PASSWORD)
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'pl')
    changeSpy.mockClear()
    await auth.logout()
    expect(changeSpy).toHaveBeenCalledTimes(1)
    expect(i18n.language).toBe('pl')

    // Ponowne wylogowanie przy zgodnych językach już niczego nie przełącza.
    await auth.logout()
    expect(changeSpy).toHaveBeenCalledTimes(1)
  })
})
