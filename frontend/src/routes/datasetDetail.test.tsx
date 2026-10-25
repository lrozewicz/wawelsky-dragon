/**
 * Trasy szczegółów datasetu na PRAWDZIWYM drzewie tras (`routeTree.gen`) — sprawdzają to,
 * czego nie widać w testach komponentów: loader zakładki woła `ensureQueryData`, a jego błąd
 * przechodzi przez `errorComponent` layoutu `/_app/dataset` (WP E3-3a T3).
 */

import { cleanup, render, screen } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { afterEach, describe, expect, it } from 'vitest'

import { createQueryClient } from '../app/queryClient'
import DialogsProvider from '../hooks/useDialogs/DialogsProvider'
import NotificationsProvider from '../hooks/useNotifications/NotificationsProvider'
import { initI18n } from '../i18n'
import { datasetHandlers, fixtureDatasetDetail } from '../test/msw/handlers'
import { server } from '../test/msw/server'
import { createTestAuth } from '../test/renderWithProviders'
import AppTheme from '../theme/AppTheme'

import { routeTree } from '../routeTree.gen'

afterEach(cleanup)

/** Montuje aplikację na prawdziwym drzewie tras — jak `main.tsx`, tyle że w pamięci. */
async function renderApp(path: string): Promise<void> {
  await initI18n('pl')
  const queryClient = createQueryClient()
  const router = createRouter({
    routeTree,
    context: { auth: createTestAuth(), queryClient },
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  await router.load().catch(() => undefined)

  render(
    <AppTheme>
      <DialogsProvider>
        <NotificationsProvider>
          <QueryClientProvider client={queryClient}>
            <RouterProvider router={router} />
          </QueryClientProvider>
        </NotificationsProvider>
      </DialogsProvider>
    </AppTheme>,
  )
}

describe('trasy szczegółów datasetu', () => {
  it('loader szczegółu z błędem pokazuje Alert z layoutu i powrót do listy', async () => {
    await renderApp('/dataset/files/brak')

    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wczytać bazy wiedzy.')
    expect(screen.getByRole('link', { name: 'Wróć do baz wiedzy' })).toHaveAttribute(
      'href',
      '/datasets',
    )
  })

  // Zakładka konfiguracji miała szkielet `EmptyState` tylko do czasu T4 — teraz wypełnia ją
  // formularz (§8.1), więc test sprawdza, że szczegół z loadera dochodzi do pól formularza.
  it('zakładka konfiguracji dostaje szczegół z loadera i wypełnia formularz', async () => {
    server.use(...datasetHandlers([fixtureDatasetDetail({ id: 'ds-1', name: 'Baza testowa' })]))

    await renderApp('/dataset/configuration/ds-1')

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Baza testowa' }),
    ).toBeInTheDocument()
    expect(await screen.findByLabelText(/Nazwa/)).toHaveValue('Baza testowa')
    expect(screen.getByRole('combobox', { name: 'Model embeddingu' })).toBeInTheDocument()
  })
})
