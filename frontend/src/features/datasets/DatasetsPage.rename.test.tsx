/**
 * Zmiana nazwy bazy na istniejącą (SC-V12-06; K20 §5 p. 1): komunikat serwera z koperty
 * RAGFlow (code 102, w. 16 INVENTORY) przepuszczony przez `lib/serverMessages` — w PL
 * „Zbiór o nazwie „X” już istnieje”, nie surowy angielski. Rozdzielone z
 * `DatasetsPage.test.tsx` przez limit 300 linii (DEC-098).
 */

import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, datasetHandlers, fixtureDatasetDetail } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { DatasetsPage } from './DatasetsPage'

afterEach(() => {
  server.resetHandlers()
})

// Trasy rejestrowane w routerze testowym (wzór: `DatasetsPage.test.tsx`).
const ROUTES = ['/datasets', '/dataset/files/$id']

const alfa = () => fixtureDatasetDetail({ id: 'ds-1', name: 'Alfa', document_count: 3 })
const beta = () => fixtureDatasetDetail({ id: 'ds-2', name: 'Beta', document_count: 1 })

describe('DatasetsPage — zmiana nazwy na istniejącą (SC-V12-06)', () => {
  it('komunikat serwera przetłumaczony przez serverMessages („Zbiór o nazwie „Beta” już istnieje”)', async () => {
    server.use(
      // Koperta RAGFlow (HTTP 200 + code 102) z w. 16 INVENTORY — wzorzec `serverMsg.datasetNameExists`.
      // Nadpisanie PUT rejestrowane PRZED `datasetHandlers` — w MSW pierwszy zarejestrowany
      // handler wygrywa, spread podstawowych handlerów rejestruje własny PUT dla tej trasy.
      http.put(apiUrl('/api/v1/datasets/:datasetId'), () =>
        HttpResponse.json({
          code: 102,
          message: "Dataset name 'Beta' already exists",
          data: null,
        }),
      ),
      ...datasetHandlers([alfa(), beta()]),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findAllByTestId('dataset-card')

    await user.click(screen.getByRole('button', { name: 'Menu bazy wiedzy Alfa' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Zmień nazwę' }))

    const dialog = await screen.findByRole('dialog')
    const field = within(dialog).getByLabelText(/Nazwa/)
    await user.clear(field)
    await user.type(field, 'Beta')
    await user.click(within(dialog).getByRole('button', { name: 'Zapisz' }))

    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('Zbiór o nazwie „Beta” już istnieje')
    expect(alert).not.toHaveTextContent("Dataset name 'Beta' already exists")
  })
})
