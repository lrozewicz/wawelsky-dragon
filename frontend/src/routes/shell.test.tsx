import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClientProvider } from '@tanstack/react-query'
import CssBaseline from '@mui/material/CssBaseline'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'

import { resetEnvCache } from '../app/env'
import { createQueryClient } from '../app/queryClient'
import DialogsProvider from '../hooks/useDialogs/DialogsProvider'
import NotificationsProvider from '../hooks/useNotifications/NotificationsProvider'
import { initI18n } from '../i18n'
import { createTestAuth } from '../test/renderWithProviders'
import AppTheme from '../theme/AppTheme'

import { routeTree } from '../routeTree.gen'

beforeEach(() => {
  localStorage.clear()
  delete window.__ENV__
  resetEnvCache()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  delete window.__ENV__
  resetEnvCache()
})

describe('powłoka aplikacji (trasa _app)', () => {
  it('renderuje menu i stronę główną bez błędów w konsoli', async () => {
    await initI18n('pl')
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const queryClient = createQueryClient()
    const router = createRouter({
      routeTree,
      // Powłoka czyta sesję i modele z kontekstu routera (E3-1b T5).
      context: { auth: createTestAuth(), queryClient },
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

    expect(await screen.findByRole('navigation', { name: 'Nawigacja główna' })).toBeInTheDocument()
    // Home (T4): baner z nickname użytkownika (08 §7.2) zamiast dawnego `home.welcome`.
    expect(screen.getByTestId('home-banner')).toHaveTextContent('Witaj w Wawelsky Dragon, User')
    expect(errorSpy).not.toHaveBeenCalled()
  })
})
