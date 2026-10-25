import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CssBaseline from '@mui/material/CssBaseline'
import { HttpResponse, http } from 'msw'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'

import { createAuthState } from '../features/auth/authState'
import type { AuthState } from '../features/auth/authState'
import type { AuthUser } from '../features/auth/authState'
import DialogsProvider from '../hooks/useDialogs/DialogsProvider'
import NotificationsProvider from '../hooks/useNotifications/NotificationsProvider'
import { i18n, initI18n } from '../i18n'
import { apiUrl, fixtureUser, logoutWithUrl } from '../test/msw/handlers'
import { server } from '../test/msw/server'
import { createTestAuth } from '../test/renderWithProviders'
import AppTheme from '../theme/AppTheme'

import { routeTree } from '../routeTree.gen'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

// Sesja, która po wylogowaniu naprawdę znika: prawdziwy `createAuthState` (POST /auth/logout,
// `localLogout`) plus znacznik odcinający guard `_app` od odtworzenia sesji z cookie.
function createSignOutAuth(): AuthState {
  const real = createAuthState({
    queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    invalidate: () => undefined,
  })
  let signedIn = true

  return {
    get user(): AuthUser | null {
      return signedIn ? real.user : null
    },
    ensureSession: async () => (signedIn ? real.ensureSession() : null),
    login: (email: string, password: string) => real.login(email, password),
    logout: async () => {
      const logoutUrl = await real.logout()
      signedIn = false
      return logoutUrl
    },
    hasRole: (role) => real.hasRole(role),
  }
}

// Powłoka `_app` na prawdziwym drzewie tras z atrapą sesji (wzór: `guards.test.tsx`).
async function renderAppShell(auth: AuthState) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  })
  const router = createRouter({
    routeTree,
    context: { auth, queryClient },
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  await router.load()

  await act(async () =>
    render(
      <AppTheme>
        <CssBaseline />
        <DialogsProvider>
          <NotificationsProvider>
            <QueryClientProvider client={queryClient}>
              <RouterProvider router={router} />
            </QueryClientProvider>
          </NotificationsProvider>
        </DialogsProvider>
      </AppTheme>,
    ),
  )

  return { router, queryClient }
}

// Menu języka w nagłówku i pozycja języka w menu użytkownika prowadzą do tej samej akcji powłoki.
async function chooseLanguage(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole('button', { name: 'Język' }))
  await user.click(screen.getByRole('menuitem', { name }))
}

describe('powłoka aplikacji — język i wylogowanie', () => {
  it('zapisuje język przez menu i przełącza i18n po sukcesie PATCH', async () => {
    await initI18n('pl')
    let patchedBody: unknown = null
    server.use(
      http.patch(apiUrl('/api/v1/users/me'), async ({ request }) => {
        patchedBody = await request.json()
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { ...fixtureUser, ...(patchedBody as Record<string, unknown>) },
        })
      }),
    )

    await renderAppShell(createTestAuth())
    const user = userEvent.setup()

    await chooseLanguage(user, 'English')

    await waitFor(() => expect(patchedBody).toEqual({ language: 'en' }))
    await waitFor(() => expect(i18n.language).toBe('en'))
  })

  it('przy błędzie zapisu języka pokazuje powiadomienie i nie zmienia języka', async () => {
    await initI18n('pl')
    server.use(
      http.patch(apiUrl('/api/v1/users/me'), () =>
        HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 }),
      ),
    )

    await renderAppShell(createTestAuth())
    const user = userEvent.setup()

    await chooseLanguage(user, 'English')

    expect(
      await screen.findByText('Nie udało się zapisać języka — spróbuj ponownie.'),
    ).toBeInTheDocument()
    expect(i18n.language).toBe('pl')
  })

  it('wylogowanie z menu użytkownika woła POST /auth/logout, auth.logout i invalidate', async () => {
    await initI18n('pl')
    const invalidate = vi.fn()
    // Atrapa `createTestAuth` z `logout` jako `vi.fn` — jej implementacją jest PRAWDZIWE
    // `createAuthState().logout()`, żeby sprawdzić cały łańcuch: kliknięcie → POST → localLogout.
    const realLogout = createAuthState({
      queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
      invalidate,
    }).logout
    const logout = vi.fn(() => realLogout())
    let logoutRequests = 0
    server.use(
      http.post(apiUrl('/api/v1/auth/logout'), () => {
        logoutRequests += 1
        return HttpResponse.json({ code: 0, message: 'success', data: true })
      }),
    )

    await renderAppShell(createTestAuth({ logout }))
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Menu użytkownika' }))
    await user.click(screen.getByRole('menuitem', { name: 'Wyloguj' }))

    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1))
    expect(logoutRequests).toBe(1)
    expect(invalidate).toHaveBeenCalledTimes(1)
  })

  it('konto OIDC: po wylogowaniu przechodzi na logout_url dostawcy tożsamości', async () => {
    await initI18n('pl')
    const logoutUrl = 'https://idp.example/logout?client_id=wawelsky-dragon'
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    server.use(logoutWithUrl(logoutUrl))

    const { router } = await renderAppShell(createSignOutAuth())
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Menu użytkownika' }))
    await user.click(screen.getByRole('menuitem', { name: 'Wyloguj' }))

    await waitFor(() => expect(assign).toHaveBeenCalledWith(logoutUrl))
    expect(router.state.location.pathname).toBe('/')
  })

  it('konto lokalne: po wylogowaniu wraca na /login', async () => {
    await initI18n('pl')
    const { router } = await renderAppShell(createSignOutAuth())
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Menu użytkownika' }))
    await user.click(screen.getByRole('menuitem', { name: 'Wyloguj' }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  })
})
