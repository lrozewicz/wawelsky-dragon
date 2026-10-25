/**
 * Testy `ChunksPanel` — lista i licznik (kontrakt WP E3-H2a §K3): filtr dostępności jedzie na
 * serwer jako `available` (bez filtra klientowego), szukanie jako `keywords`, paginacja liczy
 * 30 chunków na stronę, a stany puste i błąd mają własne teksty. Akcje (switch, zaznaczenie,
 * dialogi) mają osobny plik `ChunksPanel.actions.test.tsx`.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, chunksHandlers, fixtureChunk } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { ChunksPanel } from './ChunksPanel'
import { CHUNKS_PAGE_SIZE } from './queries'
import type { Chunk } from './queries'

afterEach(cleanup)

/** Czterdziestu kandydatów na listę — do testu paginacji (31+). */
function manyChunks(count: number): Chunk[] {
  return Array.from({ length: count }, (_value, index) =>
    fixtureChunk({ id: `c${String(index + 1)}`, content: `Treść ${String(index + 1)}` }),
  )
}

async function renderPanel(): Promise<void> {
  await renderWithProviders(
    <ChunksPanel datasetId="ds-1" docId="doc-1" onActivateChunk={() => undefined} />,
  )
}

/** Adresy żądań GET listy, w kolejności wywołań (kontrakt §ChunksPanel — wyszukiwanie, filtr, strona). */
function recordListUrls(chunks: Chunk[] = manyChunks(40)): URL[] {
  const seen: URL[] = []
  server.use(
    ...chunksHandlers(chunks, {
      onRequest: (request) => {
        if (request.method === 'GET') seen.push(new URL(request.url))
      },
    }),
  )
  return seen
}

describe('ChunksPanel', () => {
  it('pokazuje chunki z licznikiem i bez paginacji przy jednej stronie', async () => {
    server.use(
      ...chunksHandlers([
        fixtureChunk({ id: 'c1', content: 'Pierwszy' }),
        fixtureChunk({ id: 'c2', content: 'Drugi' }),
        fixtureChunk({ id: 'c3', content: 'Trzeci' }),
      ]),
    )

    await renderPanel()

    expect(await screen.findByTestId('chunk-card-c1')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^chunk-card-/)).toHaveLength(3)
    expect(screen.getByText('Wynik chunkowania')).toBeInTheDocument()
    expect(screen.getByText('3 chunki')).toBeInTheDocument()
    expect(screen.queryByTestId('chunks-pagination')).not.toBeInTheDocument()
  })

  it('filtr „Wyłączone” idzie na serwer jako `available=false` i pokazuje tylko wyłączone', async () => {
    const seen = recordListUrls([
      fixtureChunk({ id: 'c1', content: 'Włączony A' }),
      fixtureChunk({ id: 'c2', content: 'Włączony B' }),
      fixtureChunk({ id: 'c3', content: 'Wyłączony', available: false }),
    ])
    const user = userEvent.setup()

    await renderPanel()
    await screen.findByTestId('chunk-card-c1')

    await user.click(screen.getByTestId('chunks-filter-disabled'))

    await waitFor(() => expect(seen.at(-1)?.searchParams.get('available')).toBe('false'))
    expect(await screen.findByTestId('chunk-card-c3')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^chunk-card-/)).toHaveLength(1)
    // Licznik pokazuje liczbę łączną z serwera po filtrze.
    expect(screen.getByText('1 chunk')).toBeInTheDocument()
  })

  it('filtr „Włączone” wysyła `available=true`, a „Wszystkie” pomija parametr', async () => {
    const seen = recordListUrls([
      fixtureChunk({ id: 'c1', content: 'Włączony A' }),
      fixtureChunk({ id: 'c2', content: 'Wyłączony', available: false }),
    ])
    const user = userEvent.setup()

    await renderPanel()
    await screen.findByTestId('chunk-card-c1')

    await user.click(screen.getByTestId('chunks-filter-enabled'))
    await waitFor(() => expect(seen.at(-1)?.searchParams.get('available')).toBe('true'))
    expect(await screen.findByTestId('chunk-card-c1')).toBeInTheDocument()
    expect(screen.queryByTestId('chunk-card-c2')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('chunks-filter-all'))
    await waitFor(() => expect(seen.at(-1)?.searchParams.get('available')).toBeNull())
    expect(await screen.findByTestId('chunk-card-c2')).toBeInTheDocument()
  })

  it('zmiana filtra wraca na stronę 1 i czyści zaznaczenie', async () => {
    const seen = recordListUrls()
    const user = userEvent.setup()

    await renderPanel()
    await screen.findByTestId('chunk-card-c1')

    await user.click(screen.getByRole('button', { name: 'Go to page 2' }))
    await waitFor(() => expect(seen.at(-1)?.searchParams.get('page')).toBe('2'))
    await screen.findByTestId('chunk-card-c31')

    await user.click(within(screen.getByTestId('chunk-select-c31')).getByRole('checkbox'))
    expect(await screen.findByTestId('chunks-selection-bar')).toHaveTextContent('Zaznaczono')

    await user.click(screen.getByTestId('chunks-filter-enabled'))

    await waitFor(() => expect(seen.at(-1)?.searchParams.get('available')).toBe('true'))
    expect(seen.at(-1)?.searchParams.get('page')).toBe('1')
    await waitFor(() =>
      expect(screen.queryByTestId('chunks-selection-bar')).not.toBeInTheDocument(),
    )
  })

  it('wpisanie frazy wysyła ją jako `keywords` na stronę 1', async () => {
    const seen = recordListUrls()
    const user = userEvent.setup()

    await renderPanel()
    await screen.findByTestId('chunk-card-c1')

    await user.type(screen.getByTestId('chunks-search'), 'abc')

    await waitFor(() => expect(seen.at(-1)?.searchParams.get('keywords')).toBe('abc'), {
      timeout: 5000,
    })
    expect(seen.at(-1)?.searchParams.get('page')).toBe('1')
  })

  it('pokazuje 30 kart i po kliknięciu „2” żąda strony 2 z dziesięcioma kartami', async () => {
    const seen = recordListUrls()
    const user = userEvent.setup()

    await renderPanel()

    expect(await screen.findByTestId('chunk-card-c1')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^chunk-card-/)).toHaveLength(CHUNKS_PAGE_SIZE)
    expect(screen.getByTestId('chunks-pagination')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Go to page 2' }))

    await waitFor(() => expect(seen.at(-1)?.searchParams.get('page')).toBe('2'))
    expect(await screen.findByTestId('chunk-card-c31')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^chunk-card-/)).toHaveLength(10)
  })

  it('bez chunków pokazuje stan pusty listy', async () => {
    server.use(...chunksHandlers([]))

    await renderPanel()

    expect(await screen.findByTestId('empty-state')).toHaveTextContent('Brak chunków')
  })

  it('gdy filtr nic nie zostawia, stan pusty mówi o filtrze', async () => {
    server.use(...chunksHandlers([fixtureChunk({ id: 'c1' })]))
    const user = userEvent.setup()

    await renderPanel()
    await screen.findByTestId('chunk-card-c1')

    await user.click(screen.getByTestId('chunks-filter-disabled'))

    expect(await screen.findByTestId('empty-state')).toHaveTextContent(
      'Brak chunków pasujących do filtra',
    )
  })

  it('błąd listy pokazuje Alert zamiast kart', async () => {
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/documents/:documentId/chunks'), () =>
        HttpResponse.json({ code: 102, message: 'Document not found', data: null }),
      ),
    )

    await renderPanel()

    expect(await screen.findByText('Nie udało się wczytać chunków')).toBeInTheDocument()
    expect(screen.queryByTestId('chunk-card-c1')).not.toBeInTheDocument()
  })
})
