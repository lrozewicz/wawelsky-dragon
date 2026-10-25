/**
 * Akcje zbiorcze zakładki Pliki (kontrakt WP E3-3b §T7): pasek nad siatką, parsowanie (z sumą
 * chunków w `ReparseDialog`), anulowanie, włączanie i usuwanie. Zaznaczamy wiersze checkboxem
 * DataGrid; po każdej akcji pasek znika (kontrakt: zaznaczenie czyszczone). Ciała żądań zbiera
 * MSW (`documentsHandlers.onRequest`).
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, documentsHandlers, fixtureDocument } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DatasetFilesTab } from './DatasetFilesTab'

afterEach(cleanup)

const CHUNKS_ROUTE = '/chunk/parsed/chunks'

const DOC_A = fixtureDocument({ id: 'doc-1', name: 'umowa.pdf', suffix: 'pdf' })

const DOC_B = fixtureDocument({ id: 'doc-2', name: 'raport.docx', suffix: 'docx' })

/** Checkbox wiersza o podanej nazwie pliku (nagłówkowy „Zaznacz wszystkie” nas nie interesuje). */
function rowCheckbox(name: string): HTMLElement {
  const row = screen.getByText(name).closest('[role="row"]')
  if (row === null) throw new Error(`Nie znaleziono wiersza ${name}`)
  return within(row as HTMLElement).getByRole('checkbox')
}

/** Zaznacza wiersze i czeka, aż pasek zbiorczy pokaże ich liczbę. */
async function selectRows(
  user: ReturnType<typeof userEvent.setup>,
  names: string[],
): Promise<void> {
  for (const name of names) {
    await user.click(rowCheckbox(name))
  }
  expect(await screen.findByTestId('bulk-bar')).toHaveTextContent(
    `Zaznaczono: ${String(names.length)}`,
  )
}

describe('DatasetFilesTab — akcje zbiorcze', () => {
  it('Włącz wysyła batch z doc_ids i statusem 1, zaznaczenie zostaje (K6)', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC_A, DOC_B], {
        onRequest: (kind, body) => {
          if (kind === 'batch') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')
    expect(screen.queryByTestId('bulk-bar')).not.toBeInTheDocument()

    await selectRows(user, ['umowa.pdf', 'raport.docx'])
    await user.click(screen.getByTestId('bulk-enable'))

    await waitFor(() => expect(bodies).toEqual([{ doc_ids: ['doc-1', 'doc-2'], status: '1' }]))
    // Kontrakt E3-H2a §K6: po akcji zbiorczej nie czyścimy zaznaczenia — wiersze nadal istnieją.
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('Zaznaczono: 2')
  })

  it('błąd akcji zbiorczej zostawia zaznaczenie (K6)', async () => {
    server.use(
      http.post(apiUrl('/api/v1/datasets/ds-1/documents/batch-update-status'), () =>
        HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 }),
      ),
      ...documentsHandlers([DOC_A, DOC_B]),
    )

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await selectRows(user, ['umowa.pdf', 'raport.docx'])
    await user.click(screen.getByTestId('bulk-enable'))

    // T3b: komunikat serwera z koperty (nieznany — dosłownie) zamiast generyka.
    expect(await screen.findByText('boom')).toBeInTheDocument()
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('Zaznaczono: 2')
  })

  it('Parsuj bez chunków wysyła POST parse dla wszystkich zaznaczonych', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC_A, DOC_B], {
        onRequest: (kind, body) => {
          if (kind === 'parse') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await selectRows(user, ['umowa.pdf', 'raport.docx'])
    await user.click(screen.getByTestId('bulk-parse'))

    await waitFor(() => expect(bodies).toEqual([{ document_ids: ['doc-1', 'doc-2'] }]))
    expect(screen.queryByTestId('reparse-confirm')).not.toBeInTheDocument()
  })

  it('Parsuj z chunkami pokazuje dialog z ich sumą i dopiero potem parsuje', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers(
        [
          fixtureDocument({ ...DOC_A, chunk_count: 5 }),
          fixtureDocument({ ...DOC_B, chunk_count: 7 }),
        ],
        {
          onRequest: (kind, body) => {
            if (kind === 'parse') bodies.push(body)
          },
        },
      ),
    )

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await selectRows(user, ['umowa.pdf', 'raport.docx'])
    await user.click(screen.getByTestId('bulk-parse'))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Dokument ma już 12 chunków')
    expect(bodies).toEqual([])

    await user.click(screen.getByTestId('reparse-confirm'))

    await waitFor(() => expect(bodies).toEqual([{ document_ids: ['doc-1', 'doc-2'] }]))
  })

  it('Anuluj parsowanie wysyła POST stop dla zaznaczonych', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC_A, DOC_B], {
        onRequest: (kind, body) => {
          if (kind === 'stop') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await selectRows(user, ['umowa.pdf', 'raport.docx'])
    await user.click(screen.getByTestId('bulk-cancel'))

    await waitFor(() => expect(bodies).toEqual([{ document_ids: ['doc-1', 'doc-2'] }]))
  })

  it('Usuń po potwierdzeniu wysyła DELETE z zaznaczonymi ids', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC_A, DOC_B], {
        onRequest: (kind, body) => {
          if (kind === 'delete') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await selectRows(user, ['umowa.pdf', 'raport.docx'])
    await user.click(screen.getByTestId('bulk-delete'))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Usunąć zaznaczone dokumenty (2)?')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => expect(bodies).toEqual([{ ids: ['doc-1', 'doc-2'] }]))
  })

  it('Usuń melduje blokadę, gdy wszystkie zaznaczone się parsują', async () => {
    server.use(
      ...documentsHandlers([
        fixtureDocument({ ...DOC_A, run: 'RUNNING', progress: 0.4 }),
        fixtureDocument({ ...DOC_B, run: 'RUNNING', progress: 0.6 }),
      ]),
    )

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await selectRows(user, ['umowa.pdf', 'raport.docx'])
    await user.click(screen.getByTestId('bulk-delete'))

    expect(await screen.findByText('Nie można usunąć w trakcie parsowania')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('usuwanie zbiorcze pomija dokumenty w trakcie parsowania', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([fixtureDocument({ ...DOC_A, run: 'RUNNING', progress: 0.4 }), DOC_B], {
        onRequest: (kind, body) => {
          if (kind === 'delete') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await selectRows(user, ['umowa.pdf', 'raport.docx'])
    await user.click(screen.getByTestId('bulk-delete'))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Usunąć zaznaczone dokumenty (1)?')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => expect(bodies).toEqual([{ ids: ['doc-2'] }]))
    // `raport.docx` zniknął z listy, więc wypada z zaznaczenia; `umowa.pdf` zostaje (K6).
    await waitFor(() => expect(screen.getByTestId('bulk-bar')).toHaveTextContent('Zaznaczono: 1'))
  })
})
