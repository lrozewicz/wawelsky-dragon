import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { formatDate } from '../../lib/format'
import { SEARCH_TIMESTAMP, apiUrl, resetSearchesFixtures } from '../../test/msw/handlers'
import type { SearchListItem } from './queries'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { SearchesPage } from './SearchesPage'

afterEach(cleanup)
// Magazyn MSW jest wspólny dla pliku — każdy test startuje od ziarna `searchFixtureApp`.
beforeEach(resetSearchesFixtures)

// Trasy routera testowego: strona listy i cel nawigacji po utworzeniu wyszukiwarki.
const ROUTES = ['/searches', '/search/$id']

/** Podmienia listę zwracaną przez GET (mutacje nadal idą do wspólnego magazynu MSW). */
function useList(items: SearchListItem[]): void {
  server.use(
    http.get(apiUrl('/api/v1/searches'), () =>
      HttpResponse.json({
        code: 0,
        message: '',
        data: { search_apps: items, total: items.length },
      }),
    ),
  )
}

function openCardMenu(user: ReturnType<typeof userEvent.setup>) {
  return user.click(screen.getByRole('button', { name: 'Menu wyszukiwarki' }))
}

describe('SearchesPage', () => {
  it('pokazuje kartę wyszukiwarki z nazwą, datą aktualizacji i linkiem', async () => {
    await renderWithProviders(<SearchesPage />, { routes: ROUTES })

    expect(screen.getByRole('heading', { name: 'Wyszukiwarki' })).toBeInTheDocument()
    const card = await screen.findByTestId('search-card')

    expect(within(card).getByText('Wyszukiwarka testowa')).toBeInTheDocument()
    expect(within(card).getByText('W')).toBeInTheDocument()
    expect(
      within(card).getByText(`Zaktualizowano ${formatDate(SEARCH_TIMESTAMP, 'pl')}`),
    ).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: /Wyszukiwarka testowa/ })).toHaveAttribute(
      'href',
      '/search/search-1',
    )
  })

  it('bez wyszukiwarek pokazuje pusty stan z akcją tworzenia', async () => {
    useList([])

    await renderWithProviders(<SearchesPage />, { routes: ROUTES })

    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('Nie masz jeszcze wyszukiwarek')
    expect(within(empty).getByRole('button', { name: 'Utwórz wyszukiwarkę' })).toBeInTheDocument()
  })

  it('błąd listy pokazuje `query-error`, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('/api/v1/searches'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 })
        }
        return HttpResponse.json({
          code: 0,
          message: '',
          data: { search_apps: [], total: 0 },
        })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<SearchesPage />, { routes: ROUTES })

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wczytać wyszukiwarek.',
    )

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('tworzy wyszukiwarkę z nazwy i przechodzi na /search/:id', async () => {
    const user = userEvent.setup()
    const { router } = await renderWithProviders(<SearchesPage />, { routes: ROUTES })
    await screen.findByTestId('search-card')

    await user.click(screen.getByRole('button', { name: 'Utwórz wyszukiwarkę' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Nowa{Enter}')

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/search/search-2')
    })
  })

  it('zmienia nazwę wyszukiwarki z menu karty', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<SearchesPage />, { routes: ROUTES })
    await screen.findByTestId('search-card')

    await openCardMenu(user)
    await user.click(await screen.findByRole('menuitem', { name: 'Zmień nazwę' }))

    const dialog = await screen.findByRole('dialog')
    const field = within(dialog).getByLabelText(/Nazwa/)
    expect(field).toHaveValue('Wyszukiwarka testowa')

    await user.clear(field)
    await user.type(field, 'Gamma')
    await user.click(within(dialog).getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByText('Gamma')).toBeInTheDocument()
    expect(screen.queryByText('Wyszukiwarka testowa')).not.toBeInTheDocument()
  })

  it('usuwa wyszukiwarkę po potwierdzeniu', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<SearchesPage />, { routes: ROUTES })
    expect(await screen.findAllByTestId('search-card')).toHaveLength(1)

    await openCardMenu(user)
    await user.click(await screen.findByRole('menuitem', { name: 'Usuń' }))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Czy usunąć wyszukiwarkę')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => {
      expect(screen.queryAllByTestId('search-card')).toHaveLength(0)
    })
    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
  })

  it('anulowanie usuwania nie wysyła DELETE i zostawia kartę', async () => {
    let deleteCalls = 0
    server.use(
      http.delete(apiUrl('/api/v1/searches/:searchId'), () => {
        deleteCalls += 1
        return HttpResponse.json({ code: 0, message: '', data: true })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<SearchesPage />, { routes: ROUTES })
    await screen.findByTestId('search-card')

    await openCardMenu(user)
    await user.click(await screen.findByRole('menuitem', { name: 'Usuń' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Anuluj' }),
    )

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(deleteCalls).toBe(0)
    expect(screen.getByText('Wyszukiwarka testowa')).toBeInTheDocument()
  })

  it('błąd tworzenia pokazuje Alert w oknie i nie nawiguje', async () => {
    server.use(
      http.post(apiUrl('/api/v1/searches'), () =>
        HttpResponse.json({ code: 109, message: 'nazwa jest zajęta', data: false }),
      ),
    )

    const user = userEvent.setup()
    const { router } = await renderWithProviders(<SearchesPage />, { routes: ROUTES })
    await screen.findByTestId('search-card')

    await user.click(screen.getByRole('button', { name: 'Utwórz wyszukiwarkę' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Alfa{Enter}')

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('nazwa jest zajęta')
    expect(router.state.location.pathname).toBe('/')
  })

  it('błąd usuwania pokazuje komunikat nad listą', async () => {
    server.use(
      http.delete(apiUrl('/api/v1/searches/:searchId'), () =>
        HttpResponse.json({ code: 500, message: 'nie udało się usunąć' }, { status: 500 }),
      ),
    )

    const user = userEvent.setup()
    await renderWithProviders(<SearchesPage />, { routes: ROUTES })
    await screen.findByTestId('search-card')

    await openCardMenu(user)
    await user.click(await screen.findByRole('menuitem', { name: 'Usuń' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Usuń' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('nie udało się usunąć')
  })
})
