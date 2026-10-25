/**
 * Akcje wiersza zakładki Pliki (kontrakt WP E3-3b §T7): zmiana nazwy, metoda chunkowania,
 * usunięcie, parsowanie (bezpośrednio i przez `ReparseDialog`) oraz pobranie. Ciała żądań zbiera
 * MSW (`documentsHandlers.onRequest`); `downloadDocument` jest zamockowany — sprawdzamy samo
 * podpięcie, nie zapis pliku. Akcje zbiorcze mają osobny plik (`DatasetFilesTab.bulk.test.tsx`).
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { downloadDocument } from '../../../lib/download'
import { apiUrl, documentsHandlers, fixtureDocument } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DatasetFilesTab } from './DatasetFilesTab'

vi.mock('../../../lib/download', () => ({ downloadDocument: vi.fn(async () => undefined) }))

afterEach(() => {
  cleanup()
  vi.mocked(downloadDocument).mockClear()
})

const CHUNKS_ROUTE = '/chunk/parsed/chunks'

const DOC = fixtureDocument({ id: 'doc-1', name: 'umowa.pdf', suffix: 'pdf' })

const DOC_RUNNING = fixtureDocument({
  id: 'doc-1',
  name: 'duzy.pdf',
  run: 'RUNNING',
  progress: 0.3,
})

const DOC_DONE = fixtureDocument({
  id: 'doc-2',
  name: 'raport.docx',
  suffix: 'docx',
  run: 'DONE',
  progress: 1,
  chunk_count: 12,
})

describe('DatasetFilesTab — akcje wiersza', () => {
  it('zmiana nazwy wysyła PATCH z name i zamyka dialog', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC], {
        onRequest: (kind, body) => {
          if (kind === 'update') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.click(screen.getByTestId('row-rename-doc-1'))
    const input = await screen.findByTestId('rename-input')
    await user.clear(input)
    await user.type(input, 'nowa.pdf')
    await user.click(screen.getByTestId('rename-save'))

    await waitFor(() => expect(bodies).toEqual([{ name: 'nowa.pdf' }]))
    // Sukces meldujemy toastem `files.toast.renamed` (kontrakt WP E3-7 §C3/T1).
    expect(await screen.findByText('Zmieniono nazwę.')).toBeInTheDocument()
    // `Dialog` znika po animacji zamknięcia — czekamy na odmontowanie pola.
    await waitFor(() => expect(screen.queryByTestId('rename-input')).not.toBeInTheDocument())
  })

  it('zmiana metody chunkowania wysyła PATCH z chunk_method', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC], {
        onRequest: (kind, body) => {
          if (kind === 'update') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.click(screen.getByRole('button', { name: 'General' }))
    const select = await screen.findByTestId('method-select')
    await user.click(within(select).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'Table' }))
    await user.click(screen.getByTestId('method-save'))

    // Kontrakt WP E5-H8c §3: PATCH niesie też scalony parser_config dokumentu (tu domyślny).
    await waitFor(() =>
      expect(bodies).toEqual([
        { chunk_method: 'table', parser_config: { layout_recognize: 'DeepDOC', pages: [] } },
      ]),
    )
  })

  it('usunięcie dokumentu po potwierdzeniu wysyła DELETE z ids', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC], {
        onRequest: (kind, body) => {
          if (kind === 'delete') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.click(screen.getByTestId('row-delete-doc-1'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Usunąć zaznaczone dokumenty (1)?')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => expect(bodies).toEqual([{ ids: ['doc-1'] }]))
  })

  it('usuwanie jest zablokowane, gdy dokument się parsuje', async () => {
    server.use(...documentsHandlers([DOC_RUNNING]))

    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('duzy.pdf')

    expect(screen.getByTestId('row-delete-doc-1')).toBeDisabled()
  })

  it('parsowanie dokumentu bez chunków idzie od razu do POST parse', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC], {
        onRequest: (kind, body) => {
          if (kind === 'parse') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.click(screen.getByTestId('status-parse-doc-1'))

    await waitFor(() => expect(bodies).toEqual([{ document_ids: ['doc-1'] }]))
    expect(screen.queryByTestId('reparse-confirm')).not.toBeInTheDocument()
  })

  it('parsowanie dokumentu z chunkami pyta o potwierdzenie i pokazuje ich liczbę', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC_DONE], {
        onRequest: (kind, body) => {
          if (kind === 'parse') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('raport.docx')

    // Dokument DONE ma ikonę ↻ pod tym samym testidem co ▶ (kontrakt §T2: `status-parse-<id>`).
    await user.click(screen.getByTestId('status-parse-doc-2'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Dokument ma już 12 chunków')
    await user.click(screen.getByTestId('reparse-confirm'))

    await waitFor(() => expect(bodies).toEqual([{ document_ids: ['doc-2'] }]))
  })

  it('anulowanie parsowania wysyła POST stop', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC_RUNNING], {
        onRequest: (kind, body) => {
          if (kind === 'stop') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('duzy.pdf')

    await user.click(screen.getByTestId('status-stop-doc-1'))

    await waitFor(() => expect(bodies).toEqual([{ document_ids: ['doc-1'] }]))
  })

  it('pobranie woła downloadDocument dla dokumentu', async () => {
    server.use(...documentsHandlers([DOC]))

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.click(screen.getByTestId('row-download-doc-1'))

    await waitFor(() =>
      expect(downloadDocument).toHaveBeenCalledWith(
        'ds-1',
        expect.objectContaining({ id: 'doc-1', name: 'umowa.pdf' }),
      ),
    )
  })

  it('błąd mutacji pokazuje komunikat serwera (nieznany — dosłownie, T3b)', async () => {
    server.use(
      http.patch(apiUrl('/api/v1/datasets/:datasetId/documents/:documentId'), () =>
        HttpResponse.json({ code: 102, message: 'Document not found', data: null }),
      ),
      ...documentsHandlers([DOC]),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.click(screen.getByTestId('row-rename-doc-1'))
    const input = await screen.findByTestId('rename-input')
    await user.clear(input)
    await user.type(input, 'nowa.pdf')
    await user.click(screen.getByTestId('rename-save'))

    expect(await screen.findByText('Document not found')).toBeInTheDocument()
  })

  it('trasa pobrania zwraca 200 z treścią pliku', async () => {
    server.use(...documentsHandlers([DOC]))

    const response = await fetch(apiUrl('/api/v1/datasets/ds-1/documents/doc-1'))

    expect(response.status).toBe(200)
    expect(await response.text()).toBe('umowa.pdf')
  })
})
