import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, fixtureDatasetDetail, fixtureModel, modelsHandlers } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { CreateDatasetDialog } from './CreateDatasetDialog'

afterEach(cleanup)

const ROUTES = ['/datasets', '/dataset/files/$id']

// `fixtureModels.embd_id` = 'fake-embd' (domyślny model instancji) — ten model jest podpowiadany.
function embeddingModels() {
  return modelsHandlers([
    fixtureModel({ model_id: 'embd-1', name: 'fake-embd', model_type: ['embedding'] }),
    fixtureModel({ model_id: 'embd-2', name: 'other-embd', model_type: ['embedding'] }),
  ])
}

/** Okno rozwija się nad routerem testowym, bo po sukcesie oddaje `onCreated` (nawiguje strona). */
function renderDialog(onCreated: (id: string) => void = () => undefined) {
  return renderWithProviders(
    <CreateDatasetDialog onCreated={onCreated} onClose={() => undefined} />,
    {
      routes: ROUTES,
    },
  )
}

function postCapture(): { body: () => Record<string, unknown> | null } {
  let posted: Record<string, unknown> | null = null
  server.use(
    http.post(apiUrl('/api/v1/datasets'), async ({ request }) => {
      posted = (await request.json()) as Record<string, unknown>
      return HttpResponse.json({
        code: 0,
        message: 'success',
        data: fixtureDatasetDetail({ id: 'ds-9', name: 'Nowa baza' }),
      })
    }),
  )
  return { body: () => posted }
}

describe('CreateDatasetDialog', () => {
  it('walidacja U11: przycisk aktywny; klik bez nazwy pokazuje komunikat, wraca fokusem i nie wysyła', async () => {
    let posts = 0
    server.use(
      http.post(apiUrl('/api/v1/datasets'), () => {
        posts += 1
        return HttpResponse.json({ code: 0, message: 'success', data: fixtureDatasetDetail() })
      }),
      ...embeddingModels(),
    )

    const user = userEvent.setup()
    await renderDialog()

    const dialog = await screen.findByRole('dialog')
    const save = within(dialog).getByRole('button', { name: 'Utwórz' })
    expect(save).toBeEnabled()

    // Sama spacja to nadal brak nazwy (trim); Enter przy niepoprawnym formularzu nic nie wysyła.
    await user.type(within(dialog).getByLabelText(/Nazwa/), '   {Enter}')
    expect(within(dialog).getByLabelText(/Nazwa/)).toHaveFocus()
    expect(within(dialog).getByText('Podaj nazwę bazy wiedzy')).toBeInTheDocument()
    expect(posts).toBe(0)

    // Nawet programowe wysłanie formularza nie przechodzi, gdy nazwy brak (okno jest formularzem).
    fireEvent.submit(dialog)
    expect(posts).toBe(0)

    // Wpisanie nazwy gasi komunikat.
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Nowa baza')
    expect(within(dialog).queryByText('Podaj nazwę bazy wiedzy')).not.toBeInTheDocument()
  })

  it('walidacja: komunikat o wymaganej nazwie po dotknięciu pola, cisza przed nią', async () => {
    const user = userEvent.setup()
    await renderDialog()

    const dialog = await screen.findByRole('dialog')
    const name = within(dialog).getByLabelText(/Nazwa/)

    // Do pierwszej interakcji pole nie krzyczy (walidacja po dotknięciu/submit).
    expect(within(dialog).queryByText('Podaj nazwę bazy wiedzy')).not.toBeInTheDocument()

    await user.click(name)
    await user.tab()

    expect(within(dialog).getByText('Podaj nazwę bazy wiedzy')).toBeInTheDocument()

    // Wpisanie nazwy gasi komunikat.
    await user.type(name, 'Nowa baza')
    expect(within(dialog).queryByText('Podaj nazwę bazy wiedzy')).not.toBeInTheDocument()
  })

  it('walidacja U11: brak modelu embeddingu — klik pokazuje komunikat i wraca fokusem do pola', async () => {
    const onCreated = vi.fn()
    const user = userEvent.setup()
    await renderDialog(onCreated)

    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Nowa baza')

    const save = within(dialog).getByRole('button', { name: 'Utwórz' })
    expect(save).toBeEnabled()
    await user.click(save)

    expect(within(dialog).getByRole('combobox', { name: 'Model embeddingu' })).toHaveFocus()
    expect(within(dialog).getByText('Pole wymagane')).toBeInTheDocument()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('wysyła POST z wybranym modelem i metodą, a sukces oddaje przez `onCreated`', async () => {
    const captured = postCapture()
    server.use(...embeddingModels())
    const onCreated = vi.fn()

    const user = userEvent.setup()
    await renderDialog(onCreated)

    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Nowa baza')

    // Opis metody pod polem zmienia się razem z wyborem.
    expect(within(dialog).getByText(/niezależnie od typu pliku/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('combobox', { name: 'Metoda chunkowania' }))
    await user.click(await screen.findByRole('option', { name: 'Q&A' }))
    expect(within(dialog).getByText(/pary pytanie–odpowiedź/)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('combobox', { name: 'Model embeddingu' }))
    await user.click(await screen.findByRole('option', { name: 'other-embd' }))
    await user.click(within(dialog).getByRole('button', { name: 'Utwórz' }))

    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith('ds-9')
    })
    // `embedding_model` to `model_id` wybranego modelu, nie jego nazwa (kontrakt §Fakty API).
    expect(captured.body()).toEqual({
      name: 'Nowa baza',
      embedding_model: 'embd-2',
      chunk_method: 'qa',
    })
  })

  it('bez wyboru bierze domyślny model instancji i metodę General', async () => {
    const captured = postCapture()
    server.use(...embeddingModels())

    const user = userEvent.setup()
    await renderDialog()

    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Nowa baza')
    // Model domyślny dochodzi z `/users/me/models` — czekamy, aż podpowie się w polu.
    await waitFor(() => {
      expect(within(dialog).getByRole('combobox', { name: 'Model embeddingu' })).toHaveValue(
        'fake-embd',
      )
    })
    await user.click(within(dialog).getByRole('button', { name: 'Utwórz' }))

    await waitFor(() => {
      expect(captured.body()).toEqual({
        name: 'Nowa baza',
        embedding_model: 'embd-1',
        chunk_method: 'naive',
      })
    })
  })

  it('błąd tworzenia pokazuje Alert w oknie i nie oddaje sukcesu', async () => {
    server.use(
      http.post(apiUrl('/api/v1/datasets'), () =>
        HttpResponse.json({ code: 109, message: 'nazwa jest zajęta', data: false }),
      ),
      ...embeddingModels(),
    )
    const onCreated = vi.fn()

    const user = userEvent.setup()
    await renderDialog(onCreated)

    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Alfa')
    await user.click(within(dialog).getByRole('button', { name: 'Utwórz' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('nazwa jest zajęta')
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('błąd tworzenia bez treści pokazuje komunikat domyślny z i18n', async () => {
    server.use(
      // Koperta bez `message` — `ApiError` niesie pusty tekst, więc w oknie ląduje fallback.
      http.post(apiUrl('/api/v1/datasets'), () => HttpResponse.json({ code: 109, data: false })),
      ...embeddingModels(),
    )

    const user = userEvent.setup()
    await renderDialog()

    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Nowa baza')
    await user.click(within(dialog).getByRole('button', { name: 'Utwórz' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'Nie udało się utworzyć datasetu.',
    )
  })
})
