import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { formatDate } from '../../lib/format'
import {
  CHAT_TIMESTAMP,
  apiUrl,
  chatDetail,
  chatListItem,
  chatsHandlers,
} from '../../test/msw/handlers'
import type { FixtureChatListItem } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { ChatsPage } from './ChatsPage'

afterEach(cleanup)

// Trasy rejestrowane w routerze testowym: strona listy i cel nawigacji po utworzeniu czatu.
const ROUTES = ['/chats', '/chat/$id']

function alfa(): FixtureChatListItem {
  return chatListItem({ id: 'chat-1', name: 'Alfa', description: 'Opis Alfa' })
}

function beta(): FixtureChatListItem {
  return chatListItem({ id: 'chat-2', name: 'Beta', description: 'Opis Beta' })
}

function openCardMenu(user: ReturnType<typeof userEvent.setup>, name: string) {
  return user.click(screen.getByRole('button', { name: `Menu czatu ${name}` }))
}

describe('ChatsPage', () => {
  it('pokazuje kartę każdego czatu z awatarem, opisem, datą i linkiem', async () => {
    server.use(...chatsHandlers([alfa(), beta()]))

    await renderWithProviders(<ChatsPage />, { routes: ROUTES })

    expect(screen.getByRole('heading', { name: 'Czaty' })).toBeInTheDocument()
    const cards = await screen.findAllByTestId('chat-card')
    expect(cards).toHaveLength(2)

    const first = cards[0]!
    expect(within(first).getByText('Alfa')).toBeInTheDocument()
    expect(within(first).getByText('A')).toBeInTheDocument()
    expect(within(first).getByText('Opis Alfa')).toBeInTheDocument()
    expect(within(first).getByText(formatDate(CHAT_TIMESTAMP, 'pl'))).toBeInTheDocument()
    expect(within(first).getByRole('link', { name: /Alfa/ })).toHaveAttribute(
      'href',
      '/chat/chat-1',
    )
  })

  it('bez czatów pokazuje pusty stan z akcją tworzenia i ukrywa przycisk nagłówka', async () => {
    await renderWithProviders(<ChatsPage />, { routes: ROUTES })

    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('Nie masz jeszcze czatów')
    expect(within(empty).getByRole('button', { name: 'Utwórz czat' })).toBeInTheDocument()
    // SC-E5-H9-06: dokładnie jeden przycisk „Utwórz czat” — ten w nagłówku jest ukryty.
    expect(screen.getAllByRole('button', { name: 'Utwórz czat' })).toHaveLength(1)
  })

  it('błąd listy pokazuje Alert, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('/api/v1/chats'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 })
        }
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { chats: [alfa()], total: 1 },
        })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(<ChatsPage />, { routes: ROUTES })

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wczytać czatów.',
    )

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByText('Alfa')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('tworzy czat z nazwy i przechodzi na /chat/:id', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post(apiUrl('/api/v1/chats'), async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: chatDetail({ id: 'chat-2', name: 'Nowy czat' }),
        })
      }),
      ...chatsHandlers([alfa()]),
    )

    const user = userEvent.setup()
    const { router } = await renderWithProviders(<ChatsPage />, { routes: ROUTES })
    await screen.findByTestId('chat-card')

    await user.click(screen.getByRole('button', { name: 'Utwórz czat' }))
    // Tytuł okna tworzenia wg makiety SC-V13-10 — „Nowy czat” (przycisk strony zostaje „Utwórz czat”).
    const dialog = await screen.findByRole('dialog', { name: 'Nowy czat' })
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Nowy czat{Enter}')

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/chat/chat-2')
    })
    // K4/DEC-306 + K20 §5 p. 3/DEC-358: domyślne teksty nowego czatu w języku UI — powitanie
    // i odpowiedź przy braku wyników (pozostałe klucze prompt_config uzupełnia backend).
    const promptConfig = (body as { prompt_config?: unknown } | null)?.prompt_config
    expect(promptConfig).toEqual({
      prologue: 'Cześć! Jestem Twoim asystentem. W czym mogę pomóc?',
      empty_response: 'Nie znaleziono pasujących treści w bazie wiedzy.',
    })
  })

  it('?isCreate=true otwiera okno tworzenia i czyści parametr po zamknięciu', async () => {
    server.use(...chatsHandlers([alfa()]))

    const user = userEvent.setup()
    const { router } = await renderWithProviders(<ChatsPage />, {
      route: '/chats?isCreate=true',
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

  it('zmienia nazwę czatu z menu karty', async () => {
    server.use(...chatsHandlers([alfa()]))

    const user = userEvent.setup()
    await renderWithProviders(<ChatsPage />, { routes: ROUTES })
    await screen.findByTestId('chat-card')

    await openCardMenu(user, 'Alfa')
    await user.click(await screen.findByRole('menuitem', { name: 'Zmień nazwę' }))

    const dialog = await screen.findByRole('dialog')
    const field = within(dialog).getByLabelText(/Nazwa/)
    expect(field).toHaveValue('Alfa')

    await user.clear(field)
    await user.type(field, 'Gamma')
    await user.click(within(dialog).getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByText('Gamma')).toBeInTheDocument()
    expect(screen.queryByText('Alfa')).not.toBeInTheDocument()
  })

  it('usuwa czat po potwierdzeniu', async () => {
    server.use(...chatsHandlers([alfa(), beta()]))

    const user = userEvent.setup()
    await renderWithProviders(<ChatsPage />, { routes: ROUTES })
    expect(await screen.findAllByTestId('chat-card')).toHaveLength(2)

    await openCardMenu(user, 'Alfa')
    await user.click(await screen.findByRole('menuitem', { name: 'Usuń' }))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Czy usunąć czat „Alfa”?')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => {
      expect(screen.getAllByTestId('chat-card')).toHaveLength(1)
    })
    expect(screen.queryByText('Alfa')).not.toBeInTheDocument()
    expect(screen.getByText('Beta')).toBeInTheDocument()
  })

  it('anulowanie usuwania nie wysyła DELETE i zostawia kartę', async () => {
    let deleteCalls = 0
    server.use(
      http.delete(apiUrl('/api/v1/chats'), () => {
        deleteCalls += 1
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { success_count: 1, errors: null },
        })
      }),
      ...chatsHandlers([alfa()]),
    )

    const user = userEvent.setup()
    await renderWithProviders(<ChatsPage />, { routes: ROUTES })
    await screen.findByTestId('chat-card')

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

  it('błąd tworzenia pokazuje Alert w oknie i nie nawiguje', async () => {
    server.use(
      http.post(apiUrl('/api/v1/chats'), () =>
        HttpResponse.json({ code: 109, message: 'nazwa jest zajęta', data: false }),
      ),
      ...chatsHandlers([alfa()]),
    )

    const user = userEvent.setup()
    const { router } = await renderWithProviders(<ChatsPage />, { routes: ROUTES })
    await screen.findByTestId('chat-card')

    await user.click(screen.getByRole('button', { name: 'Utwórz czat' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/Nazwa/), 'Alfa{Enter}')

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('nazwa jest zajęta')
    expect(router.state.location.pathname).toBe('/')
  })

  it('błąd usuwania pokazuje komunikat nad listą', async () => {
    server.use(
      http.delete(apiUrl('/api/v1/chats'), () =>
        HttpResponse.json({ code: 500, message: 'nie udało się usunąć' }, { status: 500 }),
      ),
      ...chatsHandlers([alfa()]),
    )

    const user = userEvent.setup()
    await renderWithProviders(<ChatsPage />, { routes: ROUTES })
    await screen.findByTestId('chat-card')

    await openCardMenu(user, 'Alfa')
    await user.click(await screen.findByRole('menuitem', { name: 'Usuń' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Usuń' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('nie udało się usunąć')
  })
})
