import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import {
  apiUrl,
  chatDetail,
  chatListItem,
  chatsHandlers,
  datasetsHandlers,
  fixtureChatDatasets,
  fixtureModel,
  modelsHandlers,
} from '../../../test/msw/handlers'
import type { FixtureChatListItem } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'

import { ChatSettingsDrawer } from './ChatSettingsDrawer'

afterEach(cleanup)

/** Czat w stanie MSW (widoczny dla GET /chats/:id) + trzy bazy wiedzy z `fixtureChatDatasets`. */
function useChat(overrides: Partial<FixtureChatListItem> = {}): void {
  server.use(
    ...chatsHandlers([chatListItem({ id: 'chat-1', name: 'Alfa', ...overrides })]),
    ...datasetsHandlers(fixtureChatDatasets),
  )
}

/** Rejestr modeli `GET /api/v1/models`: dwa czatu + jeden embedding; nazwy różne od id. */
const MODEL_FIXTURES = [
  fixtureModel({ model_id: 'id-chat-1', name: 'fake-chat' }),
  fixtureModel({ model_id: 'id-chat-2', name: 'other-chat' }),
  fixtureModel({ model_id: 'id-embd', name: 'fake-embed-1024', model_type: ['embedding'] }),
]

async function renderDrawer(onClose: () => void = vi.fn()) {
  const result = await renderWithProviders(
    <ChatSettingsDrawer chatId="chat-1" open onClose={onClose} />,
  )
  await screen.findByRole('tab', { name: 'Asystent' })
  return { ...result, onClose }
}

/** Nazwa pola `GET /api/v1/datasets` używana przez multi-select baz wiedzy. */
const DATASETS_LABEL = 'Bazy wiedzy'

/** Opcja listy rozwijanej po jej widocznym tekście (nazwy MUI liczy inaczej). */
async function optionByText(text: string): Promise<HTMLElement> {
  const options = await screen.findAllByRole('option')
  const found = options.find((option) => option.textContent === text)
  if (found === undefined) throw new Error(`Brak opcji listy: ${text}`)
  return found
}

/** PATCH czatu ze sukcesem i zapisem ciała żądania — sprawdzenie, co realnie wysyła szuflada. */
function capturePatch(bodies: unknown[]) {
  return http.patch(apiUrl('/api/v1/chats/:chatId'), async ({ request }) => {
    bodies.push(await request.json())
    return HttpResponse.json({
      code: 0,
      message: 'success',
      data: chatDetail(chatListItem({ id: 'chat-1' })),
    })
  })
}

describe('ChatSettingsDrawer', () => {
  it('pokazuje trzy zakładki i przełącza ich pola', async () => {
    useChat()
    await renderDrawer()
    const user = userEvent.setup()

    expect(screen.getByRole('tab', { name: 'Asystent' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Silnik promptu' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Model' })).toBeInTheDocument()
    expect(screen.getByLabelText(/Nazwa asystenta/)).toHaveValue('Alfa')

    await user.click(screen.getByRole('tab', { name: 'Silnik promptu' }))
    expect(screen.getByLabelText(/Prompt systemowy/)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Model' }))
    expect(screen.getByRole('combobox', { name: 'Kreatywność' })).toBeInTheDocument()
  })

  it('combobox „Model” pokazuje nazwy modeli czatu, bez modeli embeddingu', async () => {
    useChat({ llm_id: 'id-chat-1' })
    server.use(...modelsHandlers(MODEL_FIXTURES))
    await renderDrawer()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Model' }))
    expect(screen.getByRole('combobox', { name: 'Model' })).toHaveValue('fake-chat')

    await user.click(screen.getByRole('combobox', { name: 'Model' }))
    expect(await screen.findByRole('option', { name: 'other-chat' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'fake-embed-1024' })).not.toBeInTheDocument()
  })

  it('wybór modelu zapisuje jego id (nie nazwę) w PATCH', async () => {
    useChat({ llm_id: 'id-chat-1' })
    server.use(...modelsHandlers(MODEL_FIXTURES))
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderDrawer()
    const user = userEvent.setup()

    await user.click(screen.getByRole('tab', { name: 'Model' }))
    await user.click(screen.getByRole('combobox', { name: 'Model' }))
    await user.click(await optionByText('other-chat'))
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ llm_id: 'id-chat-2' })
  })

  it('gdy /models nie zna bieżącego id, combobox pokazuje samo id', async () => {
    useChat({ llm_id: 'ghost-model' })
    await renderDrawer()
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Model' }))
    expect(screen.getByRole('combobox', { name: 'Model' })).toHaveValue('ghost-model')
  })

  it('wyszarza bazy z innym modelem embeddingu i bez chunków, z tooltipem', async () => {
    useChat()
    await renderDrawer()
    const user = userEvent.setup()

    // Baza bez chunków jest wyszarzona niezależnie od wyboru.
    await user.click(screen.getByRole('combobox', { name: DATASETS_LABEL }))
    expect(await optionByText('Pusta baza')).toHaveAttribute('aria-disabled', 'true')

    // Wzorzec embeddingu ustawia pierwsza wybrana baza (ds-1) — „Inny embedding” wypada.
    await user.click(await optionByText('Baza wiedzy'))
    await user.click(screen.getByRole('combobox', { name: DATASETS_LABEL }))
    const other = await optionByText('Inny embedding')
    expect(other).toHaveAttribute('aria-disabled', 'true')

    // Tooltip jest osiągalny najechaniem (bez wyłączania sprawdzania pointer-events).
    await user.hover(within(other).getByText('Inny embedding'))
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Ta baza używa innego modelu embeddingu niż wybrane bazy.',
    )

    // Klik w wyszarzoną opcję nie zmienia wyboru — stan opcji zostaje bez zmian.
    const empty = await optionByText('Pusta baza')
    expect(empty).toHaveAttribute('aria-selected', 'false')
    await user.click(within(empty).getByText('Pusta baza'))

    expect(await optionByText('Pusta baza')).toHaveAttribute('aria-selected', 'false')
    expect(await optionByText('Baza wiedzy')).toHaveAttribute('aria-selected', 'true')
  })

  it('pokazuje i zachowuje bazę czatu spoza pobranej listy (etykieta zamiast id, SC-V12-z-D3)', async () => {
    useChat({ dataset_ids: ['ds-9'] })
    await renderDrawer()

    // Niedostępna baza ma czytelną etykietę (sufiks id) — surowy id nie występuje w szufladzie.
    expect(screen.getByText('Baza niedostępna (…ds-9)')).toBeInTheDocument()
    expect(screen.queryByText('ds-9')).not.toBeInTheDocument()
  })

  it('zgłasza brak {knowledge} w prompcie, gdy wybrano bazy wiedzy', async () => {
    useChat({ dataset_ids: ['ds-1'] })
    await renderDrawer()
    const user = userEvent.setup()

    await user.click(screen.getByRole('tab', { name: 'Silnik promptu' }))
    const system = screen.getByLabelText(/Prompt systemowy/)

    expect(
      screen.getByText('Prompt systemowy musi zawierać {knowledge}, gdy wybrano bazy wiedzy.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeDisabled()

    fireEvent.change(system, { target: { value: 'Odpowiadaj z {knowledge}.' } })

    await waitFor(() =>
      expect(screen.queryByText(/musi zawierać \{knowledge\}/)).not.toBeInTheDocument(),
    )
  })

  it('zapisuje wyłącznie zmienione pola (opis) i zamyka szufladę', async () => {
    useChat()
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    const { onClose } = await renderDrawer()
    const user = userEvent.setup()

    // SC-V13-11: bez zmian „Zapisz” jest nieaktywny z powodem; zmiana gasi powód.
    const save = screen.getByRole('button', { name: 'Zapisz' })
    expect(save).toBeDisabled()
    expect(save).toHaveAttribute('aria-describedby', 'chat-settings-save-reason')
    expect(screen.getByText('Brak zmian do zapisania')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Opis'), { target: { value: 'Nowy opis' } })
    expect(save).toBeEnabled()
    expect(save.getAttribute('aria-describedby'), 'atrybut powodu zdjęty').toBeNull()
    expect(screen.queryByText('Brak zmian do zapisania')).not.toBeInTheDocument()
    await user.click(save)

    expect(await screen.findByText('Zapisano ustawienia czatu.')).toBeInTheDocument()
    expect(bodies).toEqual([{ description: 'Nowy opis' }])
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('zmiana powitania wysyła pełny prompt_config z kluczami spoza UI', async () => {
    useChat()
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderDrawer()
    const user = userEvent.setup()

    fireEvent.change(screen.getByLabelText('Powitanie'), { target: { value: 'Cześć!' } })
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({
      prompt_config: {
        prologue: 'Cześć!',
        tts: false,
        parameters: [
          { key: 'knowledge', optional: false },
          { key: 'date', optional: true },
        ],
      },
    })
    expect(Object.keys(bodies[0] as Record<string, unknown>)).toEqual(['prompt_config'])
  })

  it('błąd API pokazuje Alert z komunikatem i nie zamyka szuflady', async () => {
    useChat()
    server.use(
      http.patch(apiUrl('/api/v1/chats/:chatId'), () =>
        HttpResponse.json({ code: 102, message: 'Brak uprawnień', data: null }),
      ),
    )
    const { onClose } = await renderDrawer()
    const user = userEvent.setup()

    fireEvent.change(screen.getByLabelText('Opis'), { target: { value: 'Nowy opis' } })
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Brak uprawnień')
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Zapisz' })).toBeInTheDocument()
  })

  it('preset kreatywności ustawia wartości i zapisuje pełny llm_setting', async () => {
    useChat()
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderDrawer()
    const user = userEvent.setup()

    await user.click(screen.getByRole('tab', { name: 'Model' }))
    await user.click(screen.getByRole('combobox', { name: 'Kreatywność' }))
    await user.click(await optionByText('Improwizacja'))
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({
      llm_setting: {
        parameter: 'improvise',
        temperature: 0.8,
        top_p: 0.9,
        presence_penalty: 0.1,
        frequency_penalty: 0.1,
        max_tokens: 4096,
        temperature_enabled: false,
        top_p_enabled: false,
        presence_penalty_enabled: false,
        frequency_penalty_enabled: false,
        max_tokens_enabled: false,
      },
    })
  })

  it('akordeon „Zaawansowane” silnika promptu zmienia Top N', async () => {
    useChat()
    const bodies: unknown[] = []
    server.use(capturePatch(bodies))
    await renderDrawer()
    const user = userEvent.setup()

    await user.click(screen.getByRole('tab', { name: 'Silnik promptu' }))
    await user.click(screen.getByRole('button', { name: 'Zaawansowane' }))
    fireEvent.change(screen.getByRole('slider', { name: 'Top N' }), { target: { value: '20' } })
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ top_n: 20 })
  })
})
