import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { SessionsPanel } from './SessionsPanel'
import type { SessionsPanelProps } from './SessionsPanel'
import type { Session } from './sessionQueries'

afterEach(cleanup)

const LIST_URL = apiUrl('/api/v1/chats/chat-1/sessions')
const DETAIL_URL = apiUrl('/api/v1/chats/chat-1/sessions/:sessionId')

/** Napisy z `locales/pl/*.json` — test chodzi na interfejsie polskim (domyślnym w `renderWithProviders`). */
const SEARCH_LABEL = 'Szukaj w rozmowach'
const NEW_LABEL = 'Nowa rozmowa'
const COLLAPSE_LABEL = 'Zwiń panel rozmów'
const EXPAND_LABEL = 'Rozwiń panel rozmów'

function sessionFixture(overrides: Partial<Session> = {}): Session {
  return {
    chat_id: 'chat-1',
    create_date: '2025-01-01 00:00:00',
    create_time: 1735689600000,
    id: 's-1',
    name: 'Alfa',
    update_date: '2025-01-01 00:00:00',
    update_time: 1735689600000,
    user_id: 'u1',
    messages: [{ role: 'assistant', content: 'prologue' }],
    reference: [],
    ...overrides,
  }
}

/** Trzy rozmowy jak w przykładzie briefu: filtr 'ab' trafia tylko w „Absolut”. */
function threeSessions(): Session[] {
  return [
    sessionFixture({ id: 's-1', name: 'Alfa' }),
    sessionFixture({ id: 's-2', name: 'Absolut' }),
    sessionFixture({ id: 's-3', name: 'Beta' }),
  ]
}

type Calls = { list: number; patch: unknown[]; delete: unknown[] }

/** MSW dla trzech tras panelu (GET lista, PATCH nazwy, DELETE masowe) + licznik wywołań. */
function useSessionsApi(items: Session[]): Calls {
  const calls: Calls = { list: 0, patch: [], delete: [] }
  server.use(
    http.get(LIST_URL, () => {
      calls.list += 1
      return HttpResponse.json({ code: 0, message: 'success', data: items })
    }),
    http.patch(DETAIL_URL, async ({ request }) => {
      calls.patch.push(await request.json())
      return HttpResponse.json({
        code: 0,
        message: 'success',
        data: sessionFixture({ name: 'Nowa nazwa' }),
      })
    }),
    http.delete(LIST_URL, async ({ request }) => {
      calls.delete.push(await request.json())
      return HttpResponse.json({
        code: 0,
        message: 'success',
        data: { success_count: 1, errors: null },
      })
    }),
  )
  return calls
}

async function renderPanel(overrides: Partial<SessionsPanelProps> = {}) {
  const onSelect = vi.fn()
  const onToggleCollapsed = vi.fn()
  const result = await renderWithProviders(
    <SessionsPanel
      chatId="chat-1"
      chatName="Alfa czat"
      activeSessionId={null}
      collapsed={false}
      onSelect={onSelect}
      onToggleCollapsed={onToggleCollapsed}
      {...overrides}
    />,
  )
  return { ...result, onSelect, onToggleCollapsed }
}

/** Otwiera menu „⋮” rozmowy i zwraca jego element. */
async function openMenu(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole('button', { name: `Menu rozmowy ${name}` }))
  return screen.findByRole('menu')
}

describe('SessionsPanel', () => {
  it('pokazuje nazwę czatu, licznik rozmów i listę; aktywna jest zaznaczona', async () => {
    useSessionsApi(threeSessions())

    await renderPanel({ activeSessionId: 's-2' })

    expect(await screen.findByText('Rozmowy (3)')).toBeInTheDocument()
    expect(screen.getByText('Alfa czat')).toBeInTheDocument()
    expect(screen.getByText('A')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Alfa' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Absolut' })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('button', { name: 'Beta' })).not.toHaveAttribute('aria-current')
  })

  it('filtr po nazwie zawęża listę (bez rozróżniania wielkości liter)', async () => {
    useSessionsApi(threeSessions())
    const user = userEvent.setup()

    await renderPanel()
    await screen.findByText('Rozmowy (3)')

    await user.type(screen.getByLabelText(SEARCH_LABEL), 'ab')

    expect(await screen.findByRole('button', { name: 'Absolut' })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Alfa' })).not.toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Beta' })).not.toBeInTheDocument()
  })

  it('„+” wybiera nową sesję tymczasową przez onSelect(null)', async () => {
    useSessionsApi(threeSessions())
    const user = userEvent.setup()

    const { onSelect } = await renderPanel()
    await screen.findByText('Rozmowy (3)')

    await user.click(screen.getByRole('button', { name: NEW_LABEL }))

    expect(onSelect).toHaveBeenCalledWith(null)
  })

  it('klik w rozmowę wybiera ją przez onSelect(id)', async () => {
    useSessionsApi(threeSessions())
    const user = userEvent.setup()

    const { onSelect } = await renderPanel()
    await screen.findByText('Rozmowy (3)')

    await user.click(screen.getByRole('button', { name: 'Beta' }))

    expect(onSelect).toHaveBeenCalledWith('s-3')
  })

  it('zmiana nazwy wysyła PATCH z nową nazwą', async () => {
    const calls = useSessionsApi(threeSessions())
    const user = userEvent.setup()

    await renderPanel()
    await screen.findByText('Rozmowy (3)')

    await openMenu(user, 'Alfa')
    await user.click(screen.getByRole('menuitem', { name: 'Zmień nazwę' }))

    const dialog = await screen.findByRole('dialog')
    const field = within(dialog).getByLabelText(/Nazwa/)
    await user.clear(field)
    await user.type(field, 'Nowa nazwa{Enter}')

    await waitFor(() => {
      expect(calls.patch).toEqual([{ name: 'Nowa nazwa' }])
    })
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })

  it('usunięcie aktywnej rozmowy wysyła DELETE {ids} i czyści wybór przez onSelect(null)', async () => {
    const calls = useSessionsApi(threeSessions())
    const user = userEvent.setup()

    const { onSelect } = await renderPanel({ activeSessionId: 's-1' })
    await screen.findByText('Rozmowy (3)')

    await openMenu(user, 'Alfa')
    await user.click(screen.getByRole('menuitem', { name: 'Usuń' }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Usuń rozmowę')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => {
      expect(calls.delete).toEqual([{ ids: ['s-1'] }])
    })
    await waitFor(() => {
      expect(onSelect).toHaveBeenCalledWith(null)
    })
  })

  it('usunięcie nieaktywnej rozmowy nie zmienia wyboru', async () => {
    const calls = useSessionsApi(threeSessions())
    const user = userEvent.setup()

    const { onSelect } = await renderPanel({ activeSessionId: 's-1' })
    await screen.findByText('Rozmowy (3)')

    await openMenu(user, 'Beta')
    await user.click(screen.getByRole('menuitem', { name: 'Usuń' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => {
      expect(calls.delete).toEqual([{ ids: ['s-3'] }])
    })
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('menu rozmowy jest dostępne z klawiatury', async () => {
    useSessionsApi(threeSessions())
    const user = userEvent.setup()

    await renderPanel()
    await screen.findByText('Rozmowy (3)')

    screen.getByRole('button', { name: 'Menu rozmowy Alfa' }).focus()
    await user.keyboard('{Enter}')

    expect(await screen.findByRole('menuitem', { name: 'Zmień nazwę' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Usuń' })).toBeInTheDocument()

    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(screen.queryByRole('menuitem', { name: 'Zmień nazwę' })).not.toBeInTheDocument()
    })
  })

  it('błąd listy pokazuje Alert, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(
      http.get(LIST_URL, () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ code: 500, message: 'boom', data: null }, { status: 500 })
        }
        return HttpResponse.json({ code: 0, message: 'success', data: [sessionFixture()] })
      }),
    )
    const user = userEvent.setup()

    await renderPanel()

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wczytać rozmów.',
    )
    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByRole('button', { name: 'Alfa' })).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('bez rozmów pokazuje pusty stan', async () => {
    useSessionsApi([])

    await renderPanel()

    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('Brak rozmów')
  })

  it('zwinięty panel pokazuje tylko przycisk rozwijania', async () => {
    useSessionsApi(threeSessions())
    const user = userEvent.setup()

    const { onToggleCollapsed } = await renderPanel({ collapsed: true })

    expect(screen.getByRole('button', { name: EXPAND_LABEL })).toBeInTheDocument()
    expect(screen.queryByText(/Rozmowy \(/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(SEARCH_LABEL)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: EXPAND_LABEL }))

    expect(onToggleCollapsed).toHaveBeenCalledTimes(1)
  })

  it('rozwinięty panel ma przycisk zwijania', async () => {
    useSessionsApi(threeSessions())
    const user = userEvent.setup()

    const { onToggleCollapsed } = await renderPanel()
    await screen.findByText('Rozmowy (3)')

    await user.click(screen.getByRole('button', { name: COLLAPSE_LABEL }))

    expect(onToggleCollapsed).toHaveBeenCalledTimes(1)
  })
})
