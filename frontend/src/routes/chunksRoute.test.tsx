/**
 * Trasa strony chunków `/chunk/parsed/chunks?id=&doc_id=` na PRAWDZIWYM drzewie tras
 * (`routeTree.gen`) — sprawdza to, czego nie widać w testach komponentu: rejestrację URL,
 * walidację search params i to, że strona jest dzieckiem chronionego layoutu `/_app`
 * (kontrakt WP E3-3b §T4; od WP E3-4a T4 trasa renderuje `ChunksPage`, nie szkielet).
 */

import { cleanup, render, screen } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../app/queryClient'
import DialogsProvider from '../hooks/useDialogs/DialogsProvider'
import NotificationsProvider from '../hooks/useNotifications/NotificationsProvider'
import { initI18n } from '../i18n'
import {
  chunksHandlers,
  datasetHandlers,
  fixtureChunk,
  fixtureDatasetDetail,
} from '../test/msw/handlers'
import { server } from '../test/msw/server'
import { createTestAuth } from '../test/renderWithProviders'
import AppTheme from '../theme/AppTheme'

import { routeTree } from '../routeTree.gen'
import { chunksSearchSchema } from './_app/chunk/parsed/chunks'

// Podgląd pobiera blob — strona wystarcza zamockowana atrapa (kontrakt WP E3-4a §T4 p. 7).
vi.mock('../features/chats/preview/DocumentPreview', () => ({
  DocumentPreview: () => <div data-testid="preview-mock" />,
}))

afterEach(cleanup)

/** Strona chunków potrzebuje bazy wiedzy (breadcrumbs) i listy chunków (nazwa dokumentu). */
function useApi(): void {
  server.use(
    ...datasetHandlers([fixtureDatasetDetail({ id: 'a', name: 'Baza Alfa' })]),
    ...chunksHandlers([fixtureChunk({ id: 'c1', content: 'Treść' })]),
  )
}

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

describe('trasa chunków', () => {
  it('z `?id` i `?doc_id` renderuje stronę chunków', async () => {
    useApi()

    await renderApp('/chunk/parsed/chunks?id=a&doc_id=b')

    expect(await screen.findByTestId('chunks-page')).toBeInTheDocument()
  })

  it('brak `doc_id` nie przechodzi walidacji i nie renderuje strony', async () => {
    useApi()

    await renderApp('/chunk/parsed/chunks?id=a')

    expect(screen.queryByTestId('chunks-page')).not.toBeInTheDocument()
  })
})

describe('chunksSearchSchema', () => {
  it('wymaga obu pól jako stringów', () => {
    expect(chunksSearchSchema.safeParse({ id: 'a', doc_id: 'b' }).success).toBe(true)
    expect(chunksSearchSchema.safeParse({ id: 'a' }).success).toBe(false)
    expect(chunksSearchSchema.safeParse({ doc_id: 'b' }).success).toBe(false)
    expect(chunksSearchSchema.safeParse({}).success).toBe(false)
  })
})
