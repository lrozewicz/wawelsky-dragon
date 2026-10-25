/**
 * Pusty dymek asystenta przy `empty_response` (brief WP E5-H6a, ADDENDUM TL p. 2). Backend wysyła
 * tekst w dwóch ramkach SSE (final:false/final:true, K4 §1.4) i NIE utrwala go w sesji (K4 §3.4),
 * więc po odświeżeniu historii para live musi zostać, żeby dymek nie zniknął.
 * Osobny plik, bo `eslint` ogranicza pliki w `src/features/**` do 300 linii (DEC-098) — wzór:
 * `ChatWorkspacePage.mobile.test.tsx`.
 */

import { useState } from 'react'
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, chatListItem, chatsHandlers } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { ChatWorkspacePage } from './ChatWorkspacePage'
import type { Session } from './sessions/sessionQueries'

const CHAT_ID = 'chat-1'
const SESSIONS_URL = apiUrl('/api/v1/chats/:chatId/sessions')
const DETAIL_URL = `${SESSIONS_URL}/:sessionId`
const COMPLETIONS_URL = apiUrl('/api/v1/chats/:chatId/completions')
const SSE_HEADERS = { 'Content-Type': 'text/event-stream; charset=utf-8' }
/** Tekst „Odpowiedzi przy braku wyników”; identyfikator `m1` wiąże ramki z historią. */
const EMPTY_TEXT = 'Brak informacji w bazie'

afterEach(cleanup)

// jsdom nie implementuje `Element.scrollTo`, a lista wiadomości przewija kontener (§T5b).
beforeEach(() => {
  Object.defineProperty(Element.prototype, 'scrollTo', {
    value: vi.fn(),
    configurable: true,
    writable: true,
  })
})

/** Ramka w kształcie K4 §1.4: delta (`final:false`) i finalna (`final:true`) niosą ten sam tekst. */
const frame = (answer: string, final: boolean): string =>
  `data:${JSON.stringify({
    code: 0,
    message: '',
    data: {
      answer,
      reference: { chunks: [] },
      audio_binary: null,
      final,
      id: 'm1',
      session_id: 's7',
    },
  })}\n\n`

/**
 * Historia po zapisie (K4 §3.4): wiadomość asystenta o tym samym `id` `m1`, ale PUSTA.
 * API sesji eksponuje JEDNO `id` dla pary user+assistant — to id asystenta (`services/sessions.py`
 * `_messages`, K4 §3.3; zmierzone na stosie testowym), więc obie wiadomości mają `m1`.
 * Bez zawężenia deduplikacji do roli `assistant` trafia ona w niepustą wiadomość user.
 */
function emptyAnswerSession(): Partial<Session> {
  return {
    id: 's7',
    name: 'Hej',
    messages: [
      { role: 'user', content: 'Hej', id: 'm1' },
      { role: 'assistant', content: '', id: 'm1' },
    ],
    reference: [],
  }
}

/** Strumień otwarty do końca testu — test dokłada ramki, kiedy chce. */
function openSse() {
  const encoder = new TextEncoder()
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null
  const stream = new ReadableStream<Uint8Array>({
    start: (next) => {
      controller = next
    },
  })
  return { stream, push: (text: string) => controller?.enqueue(encoder.encode(text)) }
}

/** Atrapa trasy: `conversationId` trzyma stan (jak search w adresie) i idzie do strony propsem. */
function Workspace() {
  const [conversationId, setConversationId] = useState<string | undefined>(undefined)

  return (
    <>
      <span data-testid="conversation-id">{conversationId ?? ''}</span>
      <ChatWorkspacePage
        chatId={CHAT_ID}
        conversationId={conversationId}
        onConversationChange={(sessionId) => setConversationId(sessionId ?? undefined)}
      />
    </>
  )
}

describe('ChatWorkspacePage — empty_response', () => {
  it('po zapisie pustej treści dymek nadal pokazuje tekst z pary live', async () => {
    // Historia po zapisie: wiadomość asystenta o TYM SAMYM `id` (`m1`) i PUSTEJ treści (K4 §3.4).
    // Bez poprawki `liveInHistory` jest prawdziwe, para live znika i zostaje sam pusty dymek.
    const sse = openSse()
    server.use(
      ...chatsHandlers([chatListItem({ id: CHAT_ID, name: 'Czat Alfa' })]),
      http.get(SESSIONS_URL, () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: [{ id: 's7', name: 'Hej', messages: [], reference: [] }],
        }),
      ),
      http.get(DETAIL_URL, () =>
        HttpResponse.json({ code: 0, message: 'success', data: emptyAnswerSession() }),
      ),
      http.post(COMPLETIONS_URL, () => new HttpResponse(sse.stream, { headers: SSE_HEADERS })),
    )

    await renderWithProviders(<Workspace />)
    await screen.findByTestId('message-list')

    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText('Wpisz pytanie…'), 'Hej')
    await user.keyboard('{Enter}')
    sse.push(frame(EMPTY_TEXT, false))
    sse.push(frame(EMPTY_TEXT, true))

    // Czekamy, aż doleci historia z backendu: pusty dymek z historii + dymek live = dwa dymki.
    await waitFor(() => expect(screen.getAllByTestId('message-assistant')).toHaveLength(2))
    expect(screen.getAllByTestId('message-assistant').at(-1)).toHaveTextContent(EMPTY_TEXT)
  })
})
