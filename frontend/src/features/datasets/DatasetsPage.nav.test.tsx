/**
 * Nawigacja karty zbioru (kontrakt WP E5-H6a §C2) — wydzielona z `DatasetsPage.test.tsx`,
 * który przekracza limit `max-lines`, gdy ta para testów trafia do niego.
 * Sprawdza: zwykły klik nawiguje routerem, a klik z modyfikatorem zostaje przeglądarce.
 */
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { datasetHandlers, fixtureDatasetDetail } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { DatasetsPage } from './DatasetsPage'

afterEach(cleanup)

const ROUTES = ['/datasets', '/dataset/files/$id']

function alfa() {
  return fixtureDatasetDetail({ id: 'ds-1', name: 'Alfa', document_count: 3 })
}

function alfaCardLink() {
  return within(screen.getByTestId('dataset-card')).getByRole('link', { name: /Alfa/ })
}

describe('DatasetsPage — nawigacja kartą', () => {
  it('zwykły klik w kartę nawiguje routerem (bez przeładowania dokumentu)', async () => {
    server.use(...datasetHandlers([alfa()]))

    const user = userEvent.setup()
    const { router } = await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await user.click(alfaCardLink())

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/dataset/files/ds-1')
    })
  })

  it('klik z modyfikatorem Ctrl nie jest przechwytywany (nowa karta przeglądarki)', async () => {
    server.use(...datasetHandlers([alfa()]))

    const { router } = await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    // `fireEvent.click` zwraca `false`, gdy `preventDefault` zostało wywołane — tu ma zostać `true`.
    const notPrevented = fireEvent.click(alfaCardLink(), { ctrlKey: true, button: 0 })

    expect(notPrevented).toBe(true)
    expect(router.state.location.pathname).toBe('/')
  })
})
