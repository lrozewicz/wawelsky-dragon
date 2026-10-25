/**
 * Trasy sekcji administracyjnej na PRAWDZIWYM drzewie tras (`routeTree.gen`) — sprawdza to,
 * czego nie widać w testach komponentu: rejestrację adresów `/admin/*`, przekierowanie `/admin`
 * → `/admin/users` i działanie guardu `requireSuperuser` (kontrakt WP E3-6c2 §5).
 */

import { act, cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CssBaseline from '@mui/material/CssBaseline'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { afterEach, describe, expect, it } from 'vitest'

import type { AuthState } from '../../../features/auth/authState'
import DialogsProvider from '../../../hooks/useDialogs/DialogsProvider'
import NotificationsProvider from '../../../hooks/useNotifications/NotificationsProvider'
import { initI18n } from '../../../i18n'
import { fixtureUser } from '../../../test/msw/handlers'
import { createTestAuth } from '../../../test/renderWithProviders'
import AppTheme from '../../../theme/AppTheme'

import { routeTree } from '../../../routeTree.gen'

afterEach(cleanup)

/** Superuser — guard `requireSuperuser` czyta `auth.user.is_superuser`. */
const superuser = createTestAuth({
  user: { ...fixtureUser, is_superuser: true },
  hasRole: () => true,
})

/** Zwykły użytkownik (`fixtureUser.is_superuser === false`). */
const regularUser = createTestAuth()

// Router na prawdziwym drzewie tras z atrapą sesji (wzór: `routes/guards.test.tsx`).
async function renderAdmin(path: string, auth: AuthState = superuser) {
  await initI18n('pl')
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  })
  const router = createRouter({
    routeTree,
    context: { auth, queryClient },
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  await router.load().catch(() => undefined)

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

describe('trasy sekcji administracyjnej', () => {
  it('superuser wchodzący na /admin ląduje na /admin/users', async () => {
    const { router } = await renderAdmin('/admin')

    expect(router.state.location.pathname).toBe('/admin/users')
    expect(await screen.findByTestId('admin-users')).toBeInTheDocument()
    expect(screen.getByTestId('admin-tab-users')).toHaveAttribute('aria-selected', 'true')
  })

  it('superuser na /admin/access widzi zakładkę dostępu', async () => {
    const { router } = await renderAdmin('/admin/access')

    expect(router.state.location.pathname).toBe('/admin/access')
    expect(await screen.findByTestId('admin-access')).toBeInTheDocument()
    expect(screen.getByTestId('admin-tab-access')).toHaveAttribute('aria-selected', 'true')
  })

  it('superuser na /admin/status widzi stronę statusu', async () => {
    const { router } = await renderAdmin('/admin/status')

    expect(router.state.location.pathname).toBe('/admin/status')
    expect(await screen.findByTestId('admin-status')).toBeInTheDocument()
  })

  it('superuser na /admin/integrations widzi listę integracji i zakładkę integracji', async () => {
    const { router } = await renderAdmin('/admin/integrations')

    expect(router.state.location.pathname).toBe('/admin/integrations')
    expect(await screen.findByTestId('admin-integrations')).toBeInTheDocument()
    expect(await screen.findByText('Brak integracji')).toBeInTheDocument()
    expect(screen.getByTestId('admin-tab-integrations')).toHaveAttribute('aria-selected', 'true')
  })

  it('zwykły użytkownik z /admin/users trafia na / i nie widzi listy użytkowników', async () => {
    const { router } = await renderAdmin('/admin/users', regularUser)

    expect(router.state.location.pathname).toBe('/')
    expect(screen.queryByTestId('admin-users')).not.toBeInTheDocument()
  })

  it('zwykły użytkownik z /admin/access trafia na / i nie widzi strony dostępu', async () => {
    const { router } = await renderAdmin('/admin/access', regularUser)

    expect(router.state.location.pathname).toBe('/')
    expect(screen.queryByTestId('admin-access')).not.toBeInTheDocument()
  })

  it('zwykły użytkownik z /admin/integrations trafia na /', async () => {
    const { router } = await renderAdmin('/admin/integrations', regularUser)

    expect(router.state.location.pathname).toBe('/')
    expect(screen.queryByTestId('admin-integrations')).not.toBeInTheDocument()
  })
})
