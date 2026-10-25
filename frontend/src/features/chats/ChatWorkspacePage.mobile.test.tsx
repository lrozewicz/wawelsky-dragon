/**
 * Wąskie okno w obszarze roboczym czatu (`/chat/:id`, 08 §11; D3 z raportu QA E3-5b): kolumna
 * rozmów startuje zwinięta, zwija się po wyborze rozmowy, a zmiana progu `md` przywraca układ
 * domyślny dla szerokości. Pozostałe zachowania strony opisuje `ChatWorkspacePage.test.tsx`
 * (osobny plik, bo `eslint` ogranicza pliki w `src/features/**` do 300 linii).
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { act, cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  chatListItem,
  chatsHandlers,
  datasetsHandlers,
  fixtureChatDatasets,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { ChatWorkspacePage } from './ChatWorkspacePage'
import type { Session } from './sessions/sessionQueries'

const CHAT_ID = 'chat-mobile'
const SESSIONS_URL = apiUrl('/api/v1/chats/:chatId/sessions')
const DETAIL_URL = `${SESSIONS_URL}/:sessionId`

/** Zapytanie progu `md` (`theme.breakpoints.down('md')`) — o to samo pyta strona. */
const NARROW_QUERY = '(max-width:899.95px)'

/** Napisy z `locales/pl/*.json` — interfejs polski jest domyślny w `renderWithProviders`. */
const EXPAND_PANEL = 'Rozwiń panel rozmów'
const SEARCH_SESSIONS = 'Szukaj w rozmowach'

afterEach(cleanup)
afterEach(() => vi.unstubAllGlobals())

// jsdom nie implementuje `Element.scrollTo`, a montowana leniwie lista wiadomości przewija kontener.
beforeEach(() => {
  Object.defineProperty(Element.prototype, 'scrollTo', {
    value: vi.fn(),
    configurable: true,
    writable: true,
  })
})

/**
 * jsdom odpowiada na każde media query `false`, więc szerokość okna udajemy atrapą `matchMedia`.
 * Zwrócona funkcja woła nasłuchiwaczy zmiany — tak `useMediaQuery` dowiaduje się o nowej szerokości.
 */
function stubMatchMedia(narrow: boolean): (narrow: boolean) => void {
  const listeners = new Set<() => void>()
  let isNarrow = narrow
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      get matches() {
        return query === NARROW_QUERY && isNarrow
      },
      media: query,
      onchange: null,
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
      addListener: (listener: () => void) => listeners.add(listener),
      removeListener: (listener: () => void) => listeners.delete(listener),
      dispatchEvent: () => false,
    })),
  )
  return (next: boolean) => {
    isNarrow = next
    for (const listener of listeners) listener()
  }
}

/** Sesja z samym powitaniem — panelowi rozmów wystarczy `id`, `name`, `messages` i `reference`. */
function sessionFixture(overrides: Partial<Session> = {}): Session {
  return {
    id: 's1',
    name: 'Alfa',
    messages: [{ role: 'assistant', content: 'Cześć! W czym pomóc?' }],
    reference: [],
    ...overrides,
  } as Session
}

/** MSW: czat, lista rozmów i szczegół rozmowy — tyle czyta strona przy wąskim oknie. */
function useSessionsApi(): void {
  server.use(
    ...chatsHandlers([chatListItem({ id: CHAT_ID, name: 'Czat Alfa' })]),
    ...datasetsHandlers(fixtureChatDatasets),
    http.get(SESSIONS_URL, () =>
      HttpResponse.json({
        code: 0,
        message: 'success',
        data: [
          sessionFixture({ id: 's1', name: 'Alfa' }),
          sessionFixture({ id: 's2', name: 'Beta' }),
        ],
      }),
    ),
    http.get(DETAIL_URL, ({ params }) =>
      HttpResponse.json({
        code: 0,
        message: 'success',
        data: sessionFixture({ id: String(params.sessionId), name: 'Alfa' }),
      }),
    ),
  )
}

/** Atrapa trasy: `conversationId` trzyma stan (jak search w adresie) i idzie do strony propsem. */
function Workspace(): JSX.Element {
  const [conversationId, setConversationId] = useState<string | undefined>('s1')

  return (
    <ChatWorkspacePage
      chatId={CHAT_ID}
      conversationId={conversationId}
      onConversationChange={(sessionId) => setConversationId(sessionId ?? undefined)}
    />
  )
}

async function renderWorkspace(): Promise<void> {
  await renderWithProviders(<Workspace />)
  // Lista wiadomości jest w leniwym chunku — czekamy, aż rozmowa się zmontuje.
  await screen.findByTestId('message-list')
}

describe('ChatWorkspacePage na wąskim ekranie', () => {
  it('startuje ze zwiniętym panelem rozmów', async () => {
    stubMatchMedia(true)
    useSessionsApi()

    await renderWithProviders(<Workspace />)

    expect(screen.getByRole('button', { name: EXPAND_PANEL })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: SEARCH_SESSIONS })).not.toBeInTheDocument()
  })

  it('zwija panel po wyborze rozmowy', async () => {
    stubMatchMedia(true)
    useSessionsApi()
    const user = userEvent.setup()

    await renderWorkspace()
    await user.click(screen.getByRole('button', { name: EXPAND_PANEL }))

    await user.click(await screen.findByRole('button', { name: 'Beta' }))

    expect(await screen.findByRole('button', { name: EXPAND_PANEL })).toBeInTheDocument()
  })

  it('zwężenie okna wraca do układu domyślnego, a panel nadal można rozwinąć ręcznie', async () => {
    const resize = stubMatchMedia(false)
    useSessionsApi()
    const user = userEvent.setup()

    await renderWorkspace()
    expect(screen.getByRole('textbox', { name: SEARCH_SESSIONS })).toBeInTheDocument()

    act(() => resize(true))

    await user.click(await screen.findByRole('button', { name: EXPAND_PANEL }))

    expect(await screen.findByRole('textbox', { name: SEARCH_SESSIONS })).toBeInTheDocument()
  })
})
