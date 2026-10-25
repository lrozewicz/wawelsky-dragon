import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CssBaseline from '@mui/material/CssBaseline'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'

import type { AuthState } from '../features/auth/authState'
import DialogsProvider from '../hooks/useDialogs/DialogsProvider'
import NotificationsProvider from '../hooks/useNotifications/NotificationsProvider'
import { initI18n } from '../i18n'
import { fixtureUser } from '../test/msw/handlers'
import { createTestAuth } from '../test/renderWithProviders'
import AppTheme from '../theme/AppTheme'

import { routeTree } from '../routeTree.gen'

afterEach(cleanup)

// Router na prawdziwym drzewie tras z atrapą sesji — guardy `_app`/`_app/admin` czytają ją z kontekstu.
function createTestRouter(auth: AuthState, initialEntries: readonly string[] = ['/']) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  })
  const router = createRouter({
    routeTree,
    context: { auth, queryClient },
    history: createMemoryHistory({ initialEntries: [...initialEntries] }),
  })
  return { router, queryClient }
}

async function renderRouter(
  router: ReturnType<typeof createTestRouter>['router'],
  queryClient: QueryClient,
) {
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
}

describe('guardy tras', () => {
  it('bez sesji przekierowuje z / na /login z powrotem do /', async () => {
    await initI18n('pl')
    const { router } = createTestRouter(
      createTestAuth({ user: null, ensureSession: async () => null }),
    )

    await router.load()

    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toEqual({ redirect: '/' })
  })

  it('z sesją renderuje layout z danymi użytkownika', async () => {
    await initI18n('pl')
    const { router, queryClient } = createTestRouter(createTestAuth())

    await router.load()
    await renderRouter(router, queryClient)

    expect(await screen.findByText(fixtureUser.email)).toBeInTheDocument()
  })

  it('nie-superusera z /admin przekierowuje na /', async () => {
    await initI18n('pl')
    const { router } = createTestRouter(createTestAuth(), ['/admin'])

    await router.load()

    expect(router.state.location.pathname).toBe('/')
  })

  // Od WP E3-6c2 (T2) `/admin` jest tylko wejściem do sekcji — kieruje na pierwszą zakładkę.
  it('superuser wchodzi do sekcji /admin i ląduje na /admin/users', async () => {
    await initI18n('pl')
    const { router } = createTestRouter(
      createTestAuth({ user: { ...fixtureUser, is_superuser: true }, hasRole: () => true }),
      ['/admin'],
    )

    await router.load()

    expect(router.state.location.pathname).toBe('/admin/users')
  })

  it('nieznana ścieżka z sesją: 404 w layoucie z linkiem do baz wiedzy', async () => {
    await initI18n('pl')
    const { router, queryClient } = createTestRouter(createTestAuth(), ['/chat'])

    await router.load()
    await renderRouter(router, queryClient)

    expect(await screen.findByText('Nie znaleziono strony')).toBeInTheDocument()
    expect(screen.getByText(fixtureUser.email)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Przejdź do Baz wiedzy' })).toHaveAttribute(
      'href',
      '/datasets',
    )
  })

  it('nieznana ścieżka bez sesji przekierowuje na /login', async () => {
    await initI18n('pl')
    const { router } = createTestRouter(
      createTestAuth({ user: null, ensureSession: async () => null }),
      ['/cokolwiek'],
    )

    await router.load()

    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toEqual({ redirect: '/cokolwiek' })
  })
})
