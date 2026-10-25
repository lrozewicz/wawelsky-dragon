/**
 * Stany zapytania listy dokumentów (kontrakt WP E3-7 §C6): błąd pokazuje `QueryError`,
 * a „Spróbuj ponownie” powtarza żądanie GET i wraca do siatki.
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, fixtureDocument } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DatasetFilesTab } from './DatasetFilesTab'

afterEach(cleanup)

/** Trasa-szkielet chunków (T4) — bez niej `Link` w kolumnie Nazwa nie ma dokąd prowadzić. */
const CHUNKS_ROUTE = '/chunk/parsed/chunks'

const DOC_DONE = fixtureDocument({ id: 'doc-2', name: 'raport.docx', run: 'DONE', progress: 1 })

describe('DatasetFilesTab — stany zapytania', () => {
  it('błąd listy pokazuje `query-error`, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/documents'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ code: 101, message: 'boom', data: null })
        }
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { docs: [DOC_DONE], total: 1 },
        })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wczytać dokumentów.',
    )
    expect(screen.queryByTestId('files-grid')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByText('raport.docx')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('aktywny filtr metadanych bez trafień: stan „Brak dokumentów spełniających filtr” z akcją zdjęcia filtra (WP E6-1b §4)', async () => {
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/documents'), ({ request }) => {
        const url = new URL(request.url)
        if (url.searchParams.get('metadata_condition') !== null) {
          return HttpResponse.json({ code: 0, message: 'success', data: { docs: [], total: 0 } })
        }
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { docs: [DOC_DONE], total: 1 },
        })
      }),
      http.get(apiUrl('/api/v1/datasets/:datasetId/metadata/summary'), () =>
        HttpResponse.json({
          code: 0,
          data: { summary: { typ: { type: 'string', values: [['raport', 1]] } } },
        }),
      ),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })

    expect(await screen.findByText('raport.docx')).toBeInTheDocument()

    // Zakładanie filtra: popover → Warunek 1 → klucz `typ` → „Zastosuj” (wartość '' wystarczy
    // do niepustego parametru `metadata_condition`).
    await user.click(screen.getByTestId('metadata-filter'))
    await screen.findByRole('group', { name: 'Warunek 1' })
    await user.click(screen.getByRole('combobox', { name: 'Klucz' }))
    await user.click(await screen.findByRole('option', { name: 'typ' }))
    await user.click(screen.getByRole('button', { name: 'Zastosuj' }))

    // Stan pustego wyniku filtra: komunikat + „Wyczyść filtr”, BEZ przycisku uploadu
    // (to nie stan pustego datasetu — kontrakt WP E6-1b §4).
    expect(await screen.findByText('Brak dokumentów spełniających filtr')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Wyczyść filtr' })).toBeVisible()
    expect(screen.queryByTestId('files-add')).not.toBeInTheDocument()

    // „Wyczyść filtr” zdejmuje filtr i wraca do pełnej listy z uploadem.
    await user.click(screen.getByRole('button', { name: 'Wyczyść filtr' }))

    expect(await screen.findByText('raport.docx')).toBeInTheDocument()
    expect(screen.getByTestId('files-add')).toBeInTheDocument()
  })
})
