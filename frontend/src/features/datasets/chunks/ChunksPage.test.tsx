/**
 * Testy `ChunksPage` (kontrakty WP E3-4a §ChunksPage i WP E3-H2a §K5): breadcrumbs z nazwą bazy
 * wiedzy i dokumentu, „Wstecz” na listę plików datasetu oraz sygnał strony PDF z pozycji chunku —
 * numer strony trafia do podglądu (fragment `#page=N` w `src` iframe, sprawdzany na prawdziwym
 * `DocumentPreview`) i na atrybut `data-page` kontenera podglądu.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  chunksHandlers,
  datasetHandlers,
  fixtureChunk,
  fixtureDatasetDetail,
  fixtureDocument,
} from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { ChunksPage } from './ChunksPage'

afterEach(cleanup)

const PREVIEW_URL = apiUrl('/api/v1/documents/:documentId/preview')

// jsdom nie implementuje `URL.createObjectURL` — `DocumentPreview` tworzy z niego adres PDF-a.
const OBJECT_URL = 'blob:preview'

/** Podgląd PDF: strona renderuje prawdziwy `DocumentPreview`, więc blob musi skądś przyjść. */
function previewHandler(): HttpHandler {
  return http.get(
    PREVIEW_URL,
    () => new HttpResponse('%PDF-1.7', { headers: { 'Content-Type': 'application/pdf' } }),
  )
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => OBJECT_URL)
  URL.revokeObjectURL = vi.fn()
  // MSW działa z `onUnhandledRequest: 'error'` (kontrakt WP E3-3b §T4 p. 7) — bez handlera
  // podglądu każde żądanie `DocumentPreview` przewracałoby test.
  server.use(previewHandler())
})

/** Trasy, na które prowadzą breadcrumbs i „Wstecz” (rejestrowane jako puste cele nawigacji). */
const ROUTES = ['/datasets', '/dataset/files/$id']

/** Baza wiedzy i chunki — tyle czyta strona (nazwa dokumentu przychodzi z listy chunków). */
function useApi(chunks = [fixtureChunk({ id: 'c1', content: 'Treść' })]): void {
  server.use(
    ...datasetHandlers([fixtureDatasetDetail({ id: 'ds-1', name: 'Baza Alfa' })]),
    ...chunksHandlers(chunks),
  )
}

async function renderPage() {
  return await renderWithProviders(<ChunksPage datasetId="ds-1" docId="doc-1" />, {
    routes: ROUTES,
  })
}

describe('ChunksPage', () => {
  it('pokazuje breadcrumbs z nazwą bazy wiedzy i dokumentu oraz podgląd', async () => {
    useApi()

    await renderPage()

    const breadcrumbs = screen.getByLabelText('Ścieżka nawigacji')
    expect(await screen.findByText('Baza Alfa')).toBeInTheDocument()
    expect(await screen.findByText('plik.pdf')).toBeInTheDocument()
    expect(breadcrumbs).toHaveTextContent('Bazy wiedzy')

    expect(screen.getByTestId('chunks-preview')).toHaveTextContent('Podgląd dokumentu')
    expect(await screen.findByTitle('plik.pdf')).toBeInTheDocument()
  })

  it('„Wstecz” wraca na listę plików datasetu', async () => {
    useApi()
    const user = userEvent.setup()

    const { router } = await renderPage()
    await screen.findByTestId('chunk-card-c1')

    await user.click(screen.getByTestId('chunks-back'))

    await waitFor(() => expect(router.state.location.pathname).toBe('/dataset/files/ds-1'))
  })

  it('klik w chunk PDF podaje numer strony podglądowi (#page) i na kontener podglądu', async () => {
    useApi([fixtureChunk({ id: 'c1', content: 'Treść', positions: [[4, 1]] })])
    const user = userEvent.setup()

    await renderPage()
    const card = await screen.findByTestId('chunk-card-c1')
    expect(screen.getByTestId('chunks-preview')).not.toHaveAttribute('data-page')
    expect(await screen.findByTitle('plik.pdf')).toHaveAttribute('src', OBJECT_URL)

    await user.click(card)

    await waitFor(() => {
      expect(screen.getByTestId('chunks-preview')).toHaveAttribute('data-page', '4')
      expect(screen.getByTitle('plik.pdf')).toHaveAttribute('src', `${OBJECT_URL}#page=4`)
    })
  })

  it('dokument bez PDF nie zapisuje strony', async () => {
    server.use(
      ...datasetHandlers([fixtureDatasetDetail({ id: 'ds-1', name: 'Baza Alfa' })]),
      // Dokument DOCX: pole `type` i rozszerzenie bez `.pdf` wyłączają sygnał strony.
      http.get(apiUrl('/api/v1/datasets/:datasetId/documents/:documentId/chunks'), () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: {
            chunks: [fixtureChunk({ id: 'c1', content: 'Treść', positions: [[7, 1]] })],
            doc: {
              ...fixtureDocument({ id: 'doc-1', name: 'umowa.docx', suffix: 'docx', type: 'docx' }),
              content_hash: '',
            },
            total: 1,
          },
        }),
      ),
    )
    const user = userEvent.setup()

    await renderPage()
    const card = await screen.findByTestId('chunk-card-c1')
    expect(await screen.findByText('umowa.docx')).toBeInTheDocument()

    await user.click(card)

    expect(screen.getByTestId('chunks-preview')).not.toHaveAttribute('data-page')
  })
})
