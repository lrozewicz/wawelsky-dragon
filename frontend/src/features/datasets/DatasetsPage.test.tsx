import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  datasetHandlers,
  fixtureDatasetDetail,
  fixtureModel,
  modelsHandlers,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { DatasetsPage } from './DatasetsPage'

afterEach(cleanup)

// Trasy rejestrowane w routerze testowym: strona listy i cel nawigacji po utworzeniu datasetu.
const ROUTES = ['/datasets', '/dataset/files/$id']

const alfa = () => fixtureDatasetDetail({ id: 'ds-1', name: 'Alfa', document_count: 3 })

const beta = () => fixtureDatasetDetail({ id: 'ds-2', name: 'Beta', document_count: 1 })

// `fixtureModels.embd_id` = 'fake-embd' (domyślny model instancji) — ten model jest podpowiadany.
function embeddingModels() {
  return modelsHandlers([
    fixtureModel({ model_id: 'embd-1', name: 'fake-embd', model_type: ['embedding'] }),
    fixtureModel({ model_id: 'embd-2', name: 'other-embd', model_type: ['embedding'] }),
  ])
}

function openCardMenu(user: ReturnType<typeof userEvent.setup>, name: string) {
  return user.click(screen.getByRole('button', { name: `Menu bazy wiedzy ${name}` }))
}

// Menu karty → pozycja „Usuń” → potwierdzenie w oknie (aktywne po dojściu zapytania o powiązania — T4).
async function confirmDeleteFromCard(user: ReturnType<typeof userEvent.setup>, name: string) {
  await openCardMenu(user, name)
  await user.click(await screen.findByRole('menuitem', { name: 'Usuń' }))
  const confirm = within(await screen.findByRole('dialog')).getByTestId('delete-dataset-confirm')
  await waitFor(() => expect(confirm).toBeEnabled())
  await user.click(confirm)
}

describe('DatasetsPage', () => {
  it('pokazuje kartę każdej bazy wiedzy z awatarem, liczbą plików i linkiem', async () => {
    server.use(...datasetHandlers([alfa(), beta()]))

    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })

    expect(screen.getByRole('heading', { name: 'Bazy wiedzy' })).toBeInTheDocument()
    const cards = await screen.findAllByTestId('dataset-card')
    expect(cards).toHaveLength(2)

    const first = cards[0]!
    expect(within(first).getByText('Alfa')).toBeInTheDocument()
    expect(within(first).getByText('A')).toBeInTheDocument()
    expect(within(first).getByText('3 pliki')).toBeInTheDocument()
    expect(within(first).getByRole('link', { name: /Alfa/ })).toHaveAttribute(
      'href',
      '/dataset/files/ds-1',
    )
    expect(within(cards[1]!).getByText('1 plik')).toBeInTheDocument()
  })

  it('bez baz wiedzy pokazuje pusty stan z akcją tworzenia', async () => {
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })

    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('Nie masz jeszcze baz wiedzy')
    expect(within(empty).getByRole('button', { name: 'Utwórz dataset' })).toBeInTheDocument()
  })

  it('błąd listy pokazuje Alert, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('/api/v1/datasets'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 })
        }
        return HttpResponse.json({ code: 0, message: 'success', data: [alfa()], total_datasets: 1 })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })

    const error = await screen.findByTestId('query-error')
    expect(error).toHaveTextContent('Nie udało się wczytać baz wiedzy.')
    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByText('Alfa')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('?isCreate=true otwiera dialog tworzenia i czyści parametr po zamknięciu', async () => {
    const user = userEvent.setup()
    const { router } = await renderWithProviders(<DatasetsPage />, {
      route: '/datasets?isCreate=true',
      routes: ROUTES,
    })

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText(/Nazwa/)).toHaveValue('')
    await user.click(within(dialog).getByRole('button', { name: 'Anuluj' }))

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(router.state.location.search).toEqual({})
  })

  it('po utworzeniu datasetu przechodzi na /dataset/files/:id', async () => {
    server.use(
      http.post(apiUrl('/api/v1/datasets'), () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: fixtureDatasetDetail({ id: 'ds-9', name: 'Nowa baza' }),
        }),
      ),
      ...embeddingModels(),
      ...datasetHandlers([alfa()]),
    )

    const user = userEvent.setup()
    const { router } = await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await user.click(screen.getByRole('button', { name: 'Utwórz dataset' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Nowa baza')
    await user.click(within(dialog).getByRole('button', { name: 'Utwórz' }))

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/dataset/files/ds-9')
    })
  })

  it('zmienia nazwę bazy wiedzy z menu karty (PUT {name})', async () => {
    let updated: Record<string, unknown> | null = null
    server.use(...datasetHandlers([alfa()], { onUpdate: (body) => (updated = body) }))

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await openCardMenu(user, 'Alfa')
    await user.click(await screen.findByRole('menuitem', { name: 'Zmień nazwę' }))

    const dialog = await screen.findByRole('dialog')
    const field = within(dialog).getByLabelText(/Nazwa/)
    expect(field).toHaveValue('Alfa')
    await user.clear(field)
    await user.type(field, 'Gamma')
    await user.click(within(dialog).getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByText('Gamma')).toBeInTheDocument()
    expect(updated).toEqual({ name: 'Gamma' })
  })

  it('usuwa bazę wiedzy po potwierdzeniu (DELETE {ids})', async () => {
    let items = [alfa(), beta()]
    let deleted: Record<string, unknown> | null = null
    server.use(
      http.get(apiUrl('/api/v1/datasets'), () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: items,
          total_datasets: items.length,
        }),
      ),
      http.delete(apiUrl('/api/v1/datasets'), async ({ request }) => {
        deleted = (await request.json()) as Record<string, unknown>
        const ids = (deleted.ids ?? []) as string[]
        items = items.filter((item) => !ids.includes(item.id))
        return HttpResponse.json({ code: 0, message: 'success', data: { success_count: 1 } })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    expect(await screen.findAllByTestId('dataset-card')).toHaveLength(2)

    await openCardMenu(user, 'Alfa')
    await user.click(await screen.findByRole('menuitem', { name: 'Usuń' }))
    expect(await screen.findByRole('dialog')).toHaveTextContent('Czy usunąć bazę wiedzy „Alfa”?')
    const confirm = within(screen.getByRole('dialog')).getByTestId('delete-dataset-confirm')
    await waitFor(() => expect(confirm).toBeEnabled())
    await user.click(confirm)

    await waitFor(() => {
      expect(screen.getAllByTestId('dataset-card')).toHaveLength(1)
    })
    expect(deleted).toEqual({ ids: ['ds-1'] })
  })

  it('anulowanie usuwania nie wysyła DELETE i zostawia kartę', async () => {
    let deleteCalls = 0
    server.use(
      http.delete(apiUrl('/api/v1/datasets'), () => {
        deleteCalls += 1
        return HttpResponse.json({ code: 0, message: 'success', data: { success_count: 1 } })
      }),
      ...datasetHandlers([alfa()]),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await openCardMenu(user, 'Alfa')
    await user.click(await screen.findByRole('menuitem', { name: 'Usuń' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Anuluj' }),
    )

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(deleteCalls).toBe(0)
    expect(screen.getByText('Alfa')).toBeInTheDocument()
  })

  it('zamknięcie menu karty (Escape) nic nie robi', async () => {
    server.use(...datasetHandlers([alfa()]))

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await openCardMenu(user, 'Alfa')
    expect(await screen.findByRole('menuitem', { name: 'Usuń' })).toBeInTheDocument()
    await user.keyboard('{Escape}')

    await waitFor(() => {
      expect(screen.queryByRole('menuitem', { name: 'Usuń' })).not.toBeInTheDocument()
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('błąd zmiany nazwy pokazuje Alert w oknie', async () => {
    server.use(
      http.put(apiUrl('/api/v1/datasets/:datasetId'), () =>
        HttpResponse.json({ code: 109, message: 'nazwa jest zajęta', data: false }),
      ),
      ...datasetHandlers([alfa()]),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await openCardMenu(user, 'Alfa')
    await user.click(await screen.findByRole('menuitem', { name: 'Zmień nazwę' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Zapisz' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('nazwa jest zajęta')
  })

  it('błąd usuwania pokazuje komunikat nad listą', async () => {
    server.use(
      http.delete(apiUrl('/api/v1/datasets'), () =>
        HttpResponse.json({ code: 500, message: 'nie udało się usunąć' }, { status: 500 }),
      ),
      ...datasetHandlers([alfa()]),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await confirmDeleteFromCard(user, 'Alfa')

    expect(await screen.findByRole('alert')).toHaveTextContent('nie udało się usunąć')
  })

  it('błąd usuwania bez treści pokazuje komunikat domyślny z i18n', async () => {
    server.use(
      // Koperta bez `message` przy HTTP 200 — `ApiError` niesie pusty tekst wskutek `unwrapEnvelope`.
      http.delete(apiUrl('/api/v1/datasets'), () => HttpResponse.json({ code: 500, data: null })),
      ...datasetHandlers([alfa()]),
    )

    const user = userEvent.setup()
    await renderWithProviders(<DatasetsPage />, { routes: ROUTES })
    await screen.findByTestId('dataset-card')

    await confirmDeleteFromCard(user, 'Alfa')

    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się usunąć bazy wiedzy.')
  })
})
