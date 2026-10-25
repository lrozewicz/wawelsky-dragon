/**
 * Akcje panelu chunków (kontrakt WP E3-4a §ChunksPanel p. 3): przełącznik karty idzie
 * optymistycznie przez `useSwitchChunks`, pasek zaznaczenia przez potwierdzenie do DELETE,
 * „Nowy chunk” do POST, a edycja wysyła PATCH tylko z polami różniącymi się od oryginału.
 * Osobny plik od `ChunksPanel.test.tsx` — te testy podmieniają trasy PATCH/POST/DELETE.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, chunksHandlers, fixtureChunk } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { ChunksPanel } from './ChunksPanel'
import type { Chunk } from './queries'

afterEach(cleanup)

const CHUNKS_URL = '/api/v1/datasets/:datasetId/documents/:documentId/chunks'
const CHUNK_URL = `${CHUNKS_URL}/:chunkId`

/** Zbiera ciała żądań danej metody (listy nie mają ciała, więc filtrujemy po metodzie). */
async function renderPanelWith(initial: Chunk[], bodies: unknown[], method: string): Promise<void> {
  server.use(
    ...chunksHandlers(initial, {
      onRequest: (request) => {
        if (request.method === method) bodies.push(request.body)
      },
    }),
  )
  await renderWithProviders(
    <ChunksPanel datasetId="ds-1" docId="doc-1" onActivateChunk={() => undefined} />,
  )
}

/** `data-testid` siedzi na korzeniu kontrolki MUI — stan czytamy z wewnętrznego `input`. */
function inner(testId: string, role: string): HTMLElement {
  return within(screen.getByTestId(testId)).getByRole(role)
}

describe('ChunksPanel — akcje', () => {
  it('przełączenie Switch idzie optymistycznie i wysyła PATCH z available:false', async () => {
    const bodies: unknown[] = []
    server.use(
      // Odpowiedź opóźniona — stan po kliknięciu pochodzi z optymistycznej podmiany cache.
      http.patch(apiUrl(CHUNKS_URL), async ({ request }) => {
        bodies.push(await request.json())
        await delay(150)
        return HttpResponse.json({ code: 0, message: 'success', data: true })
      }),
      ...chunksHandlers([fixtureChunk({ id: 'c1', content: 'Treść' })]),
    )
    const user = userEvent.setup()

    await renderWithProviders(
      <ChunksPanel datasetId="ds-1" docId="doc-1" onActivateChunk={() => undefined} />,
    )
    await screen.findByTestId('chunk-card-c1')

    await user.click(inner('chunk-switch-c1', 'switch'))

    expect(inner('chunk-switch-c1', 'switch')).not.toBeChecked()
    await waitFor(() => expect(bodies).toEqual([{ chunk_ids: ['c1'], available: false }]))
  })

  it('„Zaznacz stronę” i Usuń przechodzą przez potwierdzenie do DELETE', async () => {
    const bodies: unknown[] = []
    const user = userEvent.setup()

    await renderPanelWith(
      [fixtureChunk({ id: 'c1', content: 'A' }), fixtureChunk({ id: 'c2', content: 'B' })],
      bodies,
      'DELETE',
    )
    await screen.findByTestId('chunk-card-c1')

    await user.click(inner('chunk-select-c1', 'checkbox'))
    await user.click(screen.getByTestId('chunks-select-page'))

    await user.click(screen.getByTestId('chunks-bulk-delete'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Usunąć chunki?')
    expect(dialog).toHaveTextContent('Zostanie usuniętych: 2.')

    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => expect(bodies).toEqual([{ chunk_ids: ['c1', 'c2'] }]))
  })

  it('błąd usuwania pokazuje Alert, a potwierdzenie się zamyka', async () => {
    server.use(
      http.delete(apiUrl(CHUNKS_URL), () =>
        HttpResponse.json({ code: 102, message: 'x', data: null }),
      ),
      ...chunksHandlers([fixtureChunk({ id: 'c1', content: 'A' })]),
    )
    const user = userEvent.setup()

    await renderWithProviders(
      <ChunksPanel datasetId="ds-1" docId="doc-1" onActivateChunk={() => undefined} />,
    )
    await screen.findByTestId('chunk-card-c1')

    await user.click(inner('chunk-select-c1', 'checkbox'))
    await user.click(screen.getByTestId('chunks-bulk-delete'))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    expect(await screen.findByText('Nie udało się usunąć chunków')).toBeInTheDocument()
    // `open=false` odmontowuje okno po animacji wyjścia.
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('„Nowy chunk” zapisuje się przez POST i zamyka dialog', async () => {
    const bodies: unknown[] = []
    const user = userEvent.setup()

    await renderPanelWith([], bodies, 'POST')

    await user.click(screen.getByTestId('chunks-add'))
    await user.type(screen.getByTestId('chunk-dialog-content'), 'Nowa treść')
    await user.click(screen.getByTestId('chunk-dialog-save'))

    await waitFor(() =>
      expect(bodies).toEqual([{ content: 'Nowa treść', important_keywords: [], questions: [] }]),
    )
    await waitFor(() => expect(screen.queryByTestId('chunk-dialog')).not.toBeInTheDocument())
  })

  it('edycja słowa kluczowego wysyła PATCH tylko z `important_keywords`', async () => {
    const bodies: unknown[] = []
    const user = userEvent.setup()

    await renderPanelWith(
      [fixtureChunk({ id: 'c1', content: 'Treść', important_keywords: ['a'] })],
      bodies,
      'PATCH',
    )
    await screen.findByTestId('chunk-card-c1')

    await user.click(screen.getByTestId('chunk-edit-c1'))
    await user.type(inner('chunk-dialog-keywords', 'combobox'), 'x{Enter}')
    await user.click(screen.getByTestId('chunk-dialog-save'))

    await waitFor(() => expect(bodies).toEqual([{ important_keywords: ['a', 'x'] }]))
    await waitFor(() => expect(screen.queryByTestId('chunk-dialog')).not.toBeInTheDocument())
  })

  it('zapis bez zmian zamyka dialog bez żądania', async () => {
    const bodies: unknown[] = []
    const user = userEvent.setup()

    await renderPanelWith([fixtureChunk({ id: 'c1', content: 'Treść' })], bodies, 'PATCH')
    await screen.findByTestId('chunk-card-c1')

    await user.click(screen.getByTestId('chunk-edit-c1'))
    await user.click(screen.getByTestId('chunk-dialog-save'))

    await waitFor(() => expect(screen.queryByTestId('chunk-dialog')).not.toBeInTheDocument())
    expect(bodies).toEqual([])
  })

  it('błąd zapisu pokazuje Alert, a dialog zostaje otwarty', async () => {
    server.use(
      http.patch(apiUrl(CHUNK_URL), () =>
        HttpResponse.json({ code: 102, message: 'Chunk not found', data: null }),
      ),
      ...chunksHandlers([fixtureChunk({ id: 'c1', content: 'Treść', important_keywords: ['a'] })]),
    )
    const user = userEvent.setup()

    await renderWithProviders(
      <ChunksPanel datasetId="ds-1" docId="doc-1" onActivateChunk={() => undefined} />,
    )
    await screen.findByTestId('chunk-card-c1')

    await user.click(screen.getByTestId('chunk-edit-c1'))
    await user.type(inner('chunk-dialog-keywords', 'combobox'), 'x{Enter}')
    await user.click(screen.getByTestId('chunk-dialog-save'))

    expect(await screen.findByText('Nie udało się zapisać chunku')).toBeInTheDocument()
    expect(screen.getByTestId('chunk-dialog')).toBeInTheDocument()
  })
})
