/**
 * Trasy sekcji Ustawień na PRAWDZIWYM drzewie tras (`routeTree.gen`) — sprawdza to, czego nie
 * widać w testach komponentów: rejestrację adresów `/user-setting/*` i przekierowanie
 * `/user-setting` → `/user-setting/model` (kontrakt WP E3-6c1 §4).
 * Wzór: `src/routes/_app/admin/adminRoutes.test.tsx`.
 */

import { act, cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CssBaseline from '@mui/material/CssBaseline'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import DialogsProvider from '../../../hooks/useDialogs/DialogsProvider'
import NotificationsProvider from '../../../hooks/useNotifications/NotificationsProvider'
import { initI18n } from '../../../i18n'
import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { createTestAuth } from '../../../test/renderWithProviders'
import AppTheme from '../../../theme/AppTheme'

import { routeTree } from '../../../routeTree.gen'

afterEach(cleanup)

// `ModelsPage` (T1) pyta o listę instancji dostawcy; handlery MSW Ustawień dochodzą w T2,
// więc ten plik rejestruje własną, pustą odpowiedź, żeby żądanie nie zostało nieobsłużone.
beforeEach(() => {
  server.use(
    http.get(apiUrl('/api/v1/providers/litellm/instances'), () =>
      HttpResponse.json({ code: 0, message: 'success', data: [] }),
    ),
  )
})

async function renderUserSetting(path: string) {
  await initI18n('pl')
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  })
  const router = createRouter({
    routeTree,
    context: { auth: createTestAuth(), queryClient },
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

describe('trasy sekcji Ustawień', () => {
  it('rejestruje trzy trasy zakładek i trasę sekcji', async () => {
    const { router } = await renderUserSetting('/user-setting/model')

    expect(router.routesByPath['/user-setting']).toBeDefined()
    expect(router.routesByPath['/user-setting/model']).toBeDefined()
    expect(router.routesByPath['/user-setting/profile']).toBeDefined()
    expect(router.routesByPath['/user-setting/api']).toBeDefined()
  })

  it('z /user-setting przekierowuje na /user-setting/model', async () => {
    const { router } = await renderUserSetting('/user-setting')

    expect(router.state.location.pathname).toBe('/user-setting/model')
    expect(await screen.findByTestId('settings-tab-model')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { level: 1, name: 'Ustawienia' })).toBeInTheDocument()
  })

  it('na /user-setting/profile zaznacza zakładkę Profil', async () => {
    const { router } = await renderUserSetting('/user-setting/profile')

    expect(router.state.location.pathname).toBe('/user-setting/profile')
    expect(await screen.findByTestId('settings-tab-profile')).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('na /user-setting/api zaznacza zakładkę Klucze API', async () => {
    const { router } = await renderUserSetting('/user-setting/api')

    expect(router.state.location.pathname).toBe('/user-setting/api')
    expect(await screen.findByTestId('settings-tab-api')).toHaveAttribute('aria-selected', 'true')
  })
})
