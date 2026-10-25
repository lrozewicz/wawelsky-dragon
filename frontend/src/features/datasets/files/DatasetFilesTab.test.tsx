/**
 * Zakładka „Pliki” (kontrakt WP E3-3b §T5): lista dokumentów w siatce z kolumnami §7.4,
 * filtry i paginacja serwerowa, link do chunków, stan pusty, błąd listy i dialogi
 * (przesyłanie, log parsowania). Polling i przełącznik „Włączony” mają własne pliki.
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

/** Trasa-szkielet chunków (T4) — bez niej `Link` w kolumnie Nazwa nie ma dokąd prowadzić. */
const CHUNKS_ROUTE = '/chunk/parsed/chunks'

const DOC_IDLE = fixtureDocument({ id: 'doc-1', name: 'umowa.pdf', suffix: 'pdf' })

const DOC_DONE = fixtureDocument({
  id: 'doc-2',
  name: 'raport.docx',
  suffix: 'docx',
  run: 'DONE',
  progress: 1,
  chunk_count: 12,
  progress_msg: 'Gotowe',
})

const DOC_FAIL = fixtureDocument({
  id: 'doc-3',
  name: 'dane.csv',
  suffix: 'csv',
  run: 'FAIL',
  progress: 1,
  status: '0',
  chunk_method: 'table',
})

const SUBTITLE = 'Poczekaj, aż pliki zostaną sparsowane, zanim zaczniesz czat'

describe('DatasetFilesTab', () => {
  it('pokazuje pusty stan bez dokumentów i bez podtytułu o parsowaniu', async () => {
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('Brak dokumentów')
    expect(empty).toHaveTextContent('Prześlij pierwszy plik, aby zacząć.')
    expect(screen.queryByText(SUBTITLE)).not.toBeInTheDocument()
  })

  it('podtytuł „Poczekaj…” nie pokazuje się, gdy wszystkie pliki mają status Sukces', async () => {
    server.use(...documentsHandlers([DOC_DONE]))

    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    await screen.findByText('raport.docx')
    expect(screen.queryByText(SUBTITLE)).not.toBeInTheDocument()
  })

  it('podtytuł „Poczekaj…” pokazuje się, gdy któryś plik jest w parsowaniu', async () => {
    const running = fixtureDocument({
      id: 'doc-4',
      name: 'w-toku.pdf',
      suffix: 'pdf',
      run: 'RUNNING',
      progress: 0.4,
    })
    server.use(...documentsHandlers([DOC_DONE, running]))

    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    await screen.findByText('w-toku.pdf')
    expect(screen.getByText(SUBTITLE)).toBeInTheDocument()
  })

  it('renderuje wiersze z kolumnami §7.4 dla różnych stanów parsowania', async () => {
    server.use(...documentsHandlers([DOC_IDLE, DOC_DONE, DOC_FAIL]))

    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    const doneRow = (await screen.findByText('raport.docx')).closest('[role="row"]')
    expect(doneRow).toHaveTextContent('Sukces')
    expect(doneRow).toHaveTextContent('12')
    expect(doneRow).toHaveTextContent('General')

    const failedRow = screen.getByText('dane.csv').closest('[role="row"]')
    expect(failedRow).toHaveTextContent('Błąd')
    expect(failedRow).toHaveTextContent('Table')

    // Dokument bez stanu parsowania ma przycisk ▶ zamiast tekstu statusu.
    expect(screen.getByTestId('status-parse-doc-1')).toBeInTheDocument()
  })

  it('nazwa dokumentu prowadzi do strony chunków z identyfikatorem datasetu', async () => {
    server.use(...documentsHandlers([DOC_IDLE]))

    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    const link = await screen.findByRole('link', { name: 'umowa.pdf' })
    const href = link.getAttribute('href') ?? ''
    expect(href).toContain('/chunk/parsed/chunks')
    expect(href).toContain('id=ds-1')
    expect(href).toContain('doc_id=doc-1')
  })

  it('wpisanie frazy w wyszukiwarkę wysyła keywords i wraca na stronę 1', async () => {
    const seen: URL[] = []
    server.use(
      ...documentsHandlers([DOC_IDLE], {
        onRequest: (kind, _body, url) => {
          if (kind === 'list') seen.push(url)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.type(within(screen.getByTestId('files-search')).getByRole('textbox'), 'abc')

    await waitFor(() => expect(seen.at(-1)?.searchParams.get('keywords')).toBe('abc'))
    expect(seen.at(-1)?.searchParams.get('page')).toBe('1')
  })

  it('filtr Status zawęża listę i wysyła kod run', async () => {
    const seen: URL[] = []
    server.use(
      ...documentsHandlers([DOC_IDLE, DOC_DONE], {
        onRequest: (kind, _body, url) => {
          if (kind === 'list') seen.push(url)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.click(within(screen.getByTestId('files-filter-status')).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'Sukces' }))

    await waitFor(() => expect(seen.at(-1)?.searchParams.getAll('run')).toEqual(['3']))
    expect(await screen.findByText('raport.docx')).toBeInTheDocument()
    expect(screen.queryByText('umowa.pdf')).not.toBeInTheDocument()
  })

  it('filtr Typ pliku wysyła suffix', async () => {
    const seen: URL[] = []
    server.use(
      ...documentsHandlers([DOC_IDLE, DOC_DONE], {
        onRequest: (kind, _body, url) => {
          if (kind === 'list') seen.push(url)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await user.click(within(screen.getByTestId('files-filter-type')).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'docx' }))

    await waitFor(() => expect(seen.at(-1)?.searchParams.getAll('suffix')).toEqual(['docx']))
    expect(await screen.findByText('raport.docx')).toBeInTheDocument()
  })

  it('klik w nagłówek „Data przesłania” przełącza kierunek sortowania', async () => {
    const seen: URL[] = []
    server.use(
      ...documentsHandlers([DOC_IDLE], {
        onRequest: (kind, _body, url) => {
          if (kind === 'list') seen.push(url)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')
    expect(seen.at(-1)?.searchParams.get('desc')).toBe('true')

    const header = screen.getByRole('columnheader', { name: /Data przesłania/ })
    await user.click(header)
    await waitFor(() => expect(seen.at(-1)?.searchParams.get('orderby')).toBe('create_time'))
    await waitFor(() => expect(seen.at(-1)?.searchParams.get('desc')).toBe('false'))

    await user.click(header)
    await waitFor(() => expect(seen.at(-1)?.searchParams.get('desc')).toBe('true'))
  })

  it('klik w nagłówek „Nazwa” sortuje serwerowo po nazwie (orderby=name)', async () => {
    const seen: URL[] = []
    // Ta sama data przesłania, więc początkowa kolejność to kolejność magazynu (beta, alfa).
    const docs = [
      fixtureDocument({ id: 'doc-beta', name: 'beta.pdf', suffix: 'pdf' }),
      fixtureDocument({ id: 'doc-alfa', name: 'alfa.pdf', suffix: 'pdf' }),
    ]
    server.use(
      ...documentsHandlers(docs, {
        onRequest: (kind, _body, url) => {
          if (kind === 'list') seen.push(url)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('beta.pdf')
    expect(seen.at(-1)?.searchParams.get('orderby')).toBe('create_time')

    const header = screen.getByRole('columnheader', { name: /Nazwa/ })
    await user.click(header)
    await waitFor(() => expect(seen.at(-1)?.searchParams.get('orderby')).toBe('name'))
    // Nowa kolumna wchodzi w cykl od „rosnąco”, dalej jak przy dacie (asc ↔ desc).
    await waitFor(() => expect(seen.at(-1)?.searchParams.get('desc')).toBe('false'))
    expect(
      within(screen.getByTestId('files-grid'))
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['alfa.pdf', 'beta.pdf'])

    await user.click(header)
    await waitFor(() => expect(seen.at(-1)?.searchParams.get('desc')).toBe('true'))
    expect(seen.at(-1)?.searchParams.get('orderby')).toBe('name')
    expect(
      within(screen.getByTestId('files-grid'))
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['beta.pdf', 'alfa.pdf'])
  })

  it('zmiana strony wysyła page=2', async () => {
    const seen: URL[] = []
    const docs = Array.from({ length: 12 }, (_value, index) =>
      fixtureDocument({ id: `doc-${String(index + 1)}`, name: `plik-${String(index + 1)}.pdf` }),
    )
    server.use(
      ...documentsHandlers(docs, {
        onRequest: (kind, _body, url) => {
          if (kind === 'list') seen.push(url)
        },
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('plik-1.pdf')
    expect(screen.queryByText('plik-11.pdf')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Przejdź do następnej strony' }))

    await waitFor(() => expect(seen.at(-1)?.searchParams.get('page')).toBe('2'))
    expect(await screen.findByText('plik-11.pdf')).toBeInTheDocument()
  })

  it('błąd listy pokazuje Alert, a nie siatkę', async () => {
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/documents'), () =>
        HttpResponse.json({ code: 101, message: 'boom', data: null }),
      ),
    )

    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wczytać dokumentów.',
    )
    expect(screen.queryByTestId('files-grid')).not.toBeInTheDocument()
  })

  it('„Prześlij plik” otwiera dialog przesyłania', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    await user.click(screen.getByTestId('files-add'))

    expect(await screen.findByRole('dialog')).toHaveTextContent('Prześlij pliki')
  })

  it('klik w status otwiera dialog logu parsowania', async () => {
    server.use(...documentsHandlers([DOC_DONE]))

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('raport.docx')

    await user.click(screen.getByTestId('status-log-doc-2'))

    expect(await screen.findByRole('dialog')).toHaveTextContent('Gotowe')
  })
})
