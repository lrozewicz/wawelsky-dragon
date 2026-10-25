import * as React from 'react'
import { act, render } from '@testing-library/react'
import type { RenderResult } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CssBaseline from '@mui/material/CssBaseline'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRouteWithContext,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import AppTheme from '../theme/AppTheme'
import DialogsProvider from '../hooks/useDialogs/DialogsProvider'
import NotificationsProvider from '../hooks/useNotifications/NotificationsProvider'
import { initI18n } from '../i18n'
import type { Language } from '../i18n'
import type { AuthState } from '../features/auth/authState'
import type { RouterContext } from '../app/routerContext'
import { fixtureUser } from './msw/handlers'

export type RenderWithProvidersOptions = {
  /** Ścieżka początkowa routera testowego; domyślnie '/'. */
  route?: string
  /** Dodatkowe ścieżki rejestrowane jako puste trasy, by `<Link to>` działały. */
  routes?: string[]
  /** Język interfejsu; domyślnie 'pl'. */
  language?: Language
  /** Nadpisania atrapy sesji; domyślnie zalogowany `fixtureUser`. */
  auth?: Partial<AuthState>
  /** Własny klient zapytań (np. z prepopulowanym cache). */
  queryClient?: QueryClient
}

// Testowy klient zapytań: bez ponowień i bez wyrzucania danych z cache między asercjami.
function createTestQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

// Domyślna atrapa sesji: zalogowany użytkownik z fixture MSW.
export function createTestAuth(overrides: Partial<AuthState> = {}): AuthState {
  return {
    user: fixtureUser,
    ensureSession: async () => fixtureUser,
    login: async () => fixtureUser,
    logout: async () => null,
    hasRole: (role) => role === 'superuser' && fixtureUser.is_superuser,
    ...overrides,
  }
}

// Testowy render: motyw + CssBaseline + provider dialogów, powiadomień i zapytań + router w pamięci.
// Globalny router aplikacji ma własny kontekst (`src/app/router.tsx`) — tu budujemy atrapę.
export async function renderWithProviders(
  ui: React.ReactElement,
  options: RenderWithProvidersOptions = {},
): Promise<RenderResult & { router: AnyRouter; queryClient: QueryClient }> {
  const { route = '/', routes = [], language = 'pl', auth, queryClient } = options

  await initI18n(language)

  const client = queryClient ?? createTestQueryClient()
  const context: RouterContext = { auth: createTestAuth(auth), queryClient: client }

  const rootRoute = createRootRouteWithContext<RouterContext>()({ component: () => ui })
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/',
    component: () => null,
  })

  // '/' jest już trasą indeksową — deduplikujemy, by nie tworzyć tras o tym samym id.
  const registered = new Set(['/'])
  const extraRoutes = routes
    .filter((path) => !registered.has(path) && registered.add(path))
    .map((path) => createRoute({ getParentRoute: () => rootRoute, path, component: () => null }))

  const router: AnyRouter = createRouter({
    routeTree: rootRoute.addChildren([indexRoute, ...extraRoutes]),
    context,
    history: createMemoryHistory({ initialEntries: [route] }),
  })

  await router.load()

  const result = await act(async () =>
    render(
      <AppTheme>
        <CssBaseline />
        <DialogsProvider>
          <NotificationsProvider>
            <QueryClientProvider client={client}>
              <RouterProvider router={router} />
            </QueryClientProvider>
          </NotificationsProvider>
        </DialogsProvider>
      </AppTheme>,
    ),
  )

  return { ...result, router, queryClient: client }
}
