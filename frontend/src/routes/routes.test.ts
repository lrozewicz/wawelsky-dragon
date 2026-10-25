import { createMemoryHistory, createRouter } from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'

import { createQueryClient } from '../app/queryClient'
import type { AuthState } from '../features/auth/authState'
import { createTestAuth } from '../test/renderWithProviders'

import { routeTree } from '../routeTree.gen'

// Ścieżki, które powłoka musi rejestrować. Kolejne trasy dochodzą w E3-2…E3-6.
const EXPECTED_PATHS = [
  '/',
  '/login',
  '/login-next',
  '/auth/callback',
  // Layout szczegółów datasetu i cztery zakładki (WP E3-3a T3).
  '/dataset',
  '/dataset/files/$id',
  '/dataset/retrieval/$id',
  '/dataset/logs/$id',
  '/dataset/configuration/$id',
] as const

function createTestRouter(
  initialEntries: readonly string[] = ['/'],
  auth: AuthState = createTestAuth(),
) {
  return createRouter({
    routeTree,
    // Kontekst routera z atrapą sesji — guard `_app` wymaga `auth` (E3-1b T5).
    context: { auth, queryClient: createQueryClient() },
    history: createMemoryHistory({ initialEntries: [...initialEntries] }),
  })
}

// Atrapa bez sesji — pozwala dojść do samej strony logowania, nie zatrzymując się na guardzie.
const anonymous = createTestAuth({ user: null, ensureSession: async () => null })

describe('drzewo tras', () => {
  it('rejestruje każdą oczekiwaną ścieżkę', () => {
    const router = createTestRouter()

    expect(Object.keys(router.routesByPath)).toEqual(expect.arrayContaining([...EXPECTED_PATHS]))
  })

  it('ścieżka / dopasowuje trasę powłoki _app', async () => {
    const router = createTestRouter(['/'])

    await router.load()

    expect(router.state.matches.map((match) => match.routeId)).toContain('/_app')
  })

  it('zalogowany na /login ląduje na stronie głównej', async () => {
    const router = createTestRouter(['/login'])

    await router.load()

    expect(router.state.location.pathname).toBe('/')
  })

  it('/login pokazuje formularz, gdy brak sesji', async () => {
    const router = createTestRouter(['/login'], anonymous)

    await router.load()

    expect(router.state.location.pathname).toBe('/login')
  })

  it('/login-next przekierowuje na /login', async () => {
    const router = createTestRouter(['/login-next'], anonymous)

    await router.load()

    expect(router.state.location.pathname).toBe('/login')
  })
})

describe('callback OIDC', () => {
  it('odtwarza sesję i przechodzi na cel z `redirect`', async () => {
    const router = createTestRouter(['/auth/callback?redirect=/chat'])

    await router.load()

    // `/chat` dojdzie w E3-6; tu liczy się sam cel przekierowania.
    expect(router.state.location.pathname).toBe('/chat')
  })

  it('odrzuca cel protokoło-względny i ląduje na stronie głównej', async () => {
    const router = createTestRouter(['/auth/callback?redirect=//evil'])

    await router.load()

    expect(router.state.location.pathname).toBe('/')
  })

  it('bez sesji wraca na /login', async () => {
    const router = createTestRouter(['/auth/callback'], anonymous)

    await router.load()

    expect(router.state.location.pathname).toBe('/login')
  })

  it('przekazuje slug błędu na /login', async () => {
    const router = createTestRouter(['/auth/callback?error=invalid_state'], anonymous)

    await router.load()

    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toMatchObject({ error: 'invalid_state' })
  })
})
