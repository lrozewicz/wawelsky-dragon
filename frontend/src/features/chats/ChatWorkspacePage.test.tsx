import { useState } from 'react'
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { components } from '../../api/schema.gen'
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

type ReferenceChunk = components['schemas']['ReferenceChunk']

// Napisy pochodzą z `locales/pl/*.json` — interfejs polski jest domyślny w `renderWithProviders`:
// pole pytania (`Wpisz pytanie…`), Stop (`Zatrzymaj`), ponowienie (`Wygeneruj ponownie`),
// opinia (`Odpowiedź pomocna`), nagłówek rozmowy tymczasowej (`Nowa rozmowa`), status po Stopie.
const CHAT_ID = 'chat-1'
const SESSIONS_URL = apiUrl('/api/v1/chats/:chatId/sessions')
const DETAIL_URL = `${SESSIONS_URL}/:sessionId`
const COMPLETIONS_URL = apiUrl('/api/v1/chats/:chatId/completions')
const FEEDBACK_URL = `${DETAIL_URL}/messages/:messageId/feedback`
const PREVIEW_URL = apiUrl('/api/v1/documents/:documentId/preview')
const SSE_HEADERS = { 'Content-Type': 'text/event-stream; charset=utf-8' }

afterEach(cleanup)

// jsdom nie implementuje `Element.scrollTo`, a lista wiadomości przewija kontener (§T5b).
beforeEach(() => {
  Object.defineProperty(Element.prototype, 'scrollTo', {
    value: vi.fn(),
    configurable: true,
    writable: true,
  })
})

/** Ramka w kształcie K4 §1.2 — jak w `useChatStream.test.tsx`. */
const frame = (data: unknown): string =>
  `data:${JSON.stringify({ code: 0, message: '', data })}\n\n`

const delta = (answer: string, sessionId: string): string =>
  frame({
    answer,
    reference: { chunks: [] },
    audio_binary: null,
    final: false,
    id: 'm1',
    session_id: sessionId,
    chat_id: CHAT_ID,
  })

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

/** Sesja z samym powitaniem; strona czyta z niej `id`, `name`, `messages` i `reference`. */
function sessionFixture(overrides: Partial<Session> = {}): Session {
  return {
    id: 's1',
    name: 'Alfa',
    messages: [{ role: 'assistant', content: 'Cześć! W czym pomóc?' }],
    reference: [],
    ...overrides,
  } as Session
}

/** Historia z odpowiedzią niosącą znacznik cytowania `[ID:0]` (reduktor czyta tylko te pola chunku). */
function citationSession(): Session {
  const chunk = {
    id: 'c1',
    content: 'Smok wawelski mieszkał w jaskini pod wzgórzem.',
    document_id: 'doc-1',
    document_name: 'Smok.pdf',
    similarity: 0.87,
  } as ReferenceChunk

  return sessionFixture({
    messages: [
      { role: 'assistant', content: 'Cześć! W czym pomóc?' },
      { role: 'user', content: 'Kim jest smok?', id: 'u1' },
      { role: 'assistant', content: 'Smok mieszka na Wawelu [ID:0].', id: 'a1' },
    ],
    reference: [{ chunks: [chunk], total: 1 }],
  })
}

/** MSW obszaru roboczego (czat, rozmowy, kompletacje jako strumień, opinia, podgląd) + rejestr wywołań. */
function useWorkspaceApi(detail?: (sessionId: string) => Session) {
  const api = {
    completions: [] as { question: string; session_id: string | null }[],
    feedback: [] as unknown[],
    // Liczba pobrań pliku podglądu — strażnik DEC-269: rośnie dopiero po „Otwórz dokument”.
    preview: 0,
    sse: openSse(),
  }

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
    http.get(DETAIL_URL, ({ params }) => {
      const sessionId = String(params.sessionId)
      // Nazwy zgodne z listą rozmów — nagłówek kolumny pokazuje nazwę sesji.
      const session =
        detail?.(sessionId) ??
        sessionFixture({ id: sessionId, name: sessionId === 's2' ? 'Beta' : 'Alfa' })
      return HttpResponse.json({ code: 0, message: 'success', data: session })
    }),
    http.post(COMPLETIONS_URL, async ({ request }) => {
      api.completions.push(
        (await request.json()) as { question: string; session_id: string | null },
      )
      return new HttpResponse(api.sse.stream, { headers: SSE_HEADERS })
    }),
    http.put(FEEDBACK_URL, async ({ request }) => {
      api.feedback.push(await request.json())
      return HttpResponse.json({ code: 0, message: 'success', data: sessionFixture() })
    }),
    http.get(PREVIEW_URL, () => {
      api.preview += 1
      return new HttpResponse('Smok wawelski mieszkał w jaskini.', {
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      })
    }),
  )

  return api
}

/** Atrapa trasy: `conversationId` trzyma stan (jak search w adresie) i idzie do strony propsem. */
function Workspace(props: { chatId?: string; conversationId?: string }) {
  const [conversationId, setConversationId] = useState(props.conversationId)

  return (
    <>
      <span data-testid="conversation-id">{conversationId ?? ''}</span>
      <ChatWorkspacePage
        chatId={props.chatId ?? CHAT_ID}
        conversationId={conversationId}
        onConversationChange={(sessionId) => setConversationId(sessionId ?? undefined)}
      />
    </>
  )
}

async function renderWorkspace(conversationId?: string) {
  await renderWithProviders(<Workspace conversationId={conversationId} />)
  // Lista wiadomości jest w leniwym chunku — czekamy, aż rozmowa się zmontuje.
  await screen.findByTestId('message-list')
}

/** Wpisuje pytanie w polu rozmowy i wysyła je Enterem. */
async function ask(user: ReturnType<typeof userEvent.setup>, text: string): Promise<void> {
  await user.type(screen.getByPlaceholderText('Wpisz pytanie…'), text)
  await user.keyboard('{Enter}')
}

describe('ChatWorkspacePage', () => {
  it('pierwsze pytanie leci bez session_id, a sesja z pierwszej ramki trafia do adresu', async () => {
    const api = useWorkspaceApi((sessionId) =>
      sessionFixture({
        id: sessionId,
        name: 'Hej',
        messages: [
          { role: 'user', content: 'Hej', id: 'u1' },
          { role: 'assistant', content: 'Cześć', id: 'm1' },
        ],
      }),
    )
    const user = userEvent.setup()
    await renderWorkspace()

    expect(screen.getByText('Nowa rozmowa')).toBeInTheDocument()

    await ask(user, 'Hej')

    await waitFor(() => expect(api.completions).toHaveLength(1))
    expect(api.completions[0]).toMatchObject({ question: 'Hej', session_id: null })

    api.sse.push(delta('Cześć', 's7'))

    await waitFor(() => expect(screen.getByTestId('conversation-id')).toHaveTextContent('s7'))
    // Historia z adresu niesie już tę samą wiadomość (`m1`) — para live jest deduplikowana.
    await waitFor(() => expect(screen.getAllByText('Cześć')).toHaveLength(1))
  })

  it('dopisuje przyrost odpowiedzi, Stop przerywa, a zmiana rozmowy porzuca wymianę', async () => {
    const api = useWorkspaceApi()
    const user = userEvent.setup()
    await renderWorkspace('s1')

    await ask(user, 'Kim jest smok?')
    await waitFor(() => expect(api.completions).toHaveLength(1))
    api.sse.push(delta('Smok ', 's1'))
    expect(await screen.findByText('Smok')).toBeInTheDocument()
    api.sse.push(delta('mieszka na Wawelu', 's1'))
    expect(await screen.findByText('Smok mieszka na Wawelu')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Zatrzymaj' }))
    expect(await screen.findByText('Przerwano')).toBeInTheDocument()
    expect(screen.getByText('Smok mieszka na Wawelu')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Beta' }))
    await waitFor(() => expect(screen.getByTestId('conversation-id')).toHaveTextContent('s2'))
    await waitFor(() => expect(screen.queryByText('Smok mieszka na Wawelu')).toBeNull())
    expect(await screen.findByRole('heading', { name: 'Beta' })).toBeInTheDocument()
  })

  it('wczytuje historię z ?conversationId=, a „Otwórz dokument” z dialogu cytowania otwiera szufladę', async () => {
    const api = useWorkspaceApi(() => citationSession())
    const user = userEvent.setup()

    await renderWorkspace('s1')

    const answers = await screen.findAllByTestId('message-assistant')
    expect(within(answers.at(-1)!).getByText(/Smok mieszka na Wawelu/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Alfa' })).toBeInTheDocument()

    // Podgląd cytatu (DEC-269) jest lokalny — plik dokumentu pobiera dopiero „Otwórz dokument”.
    await user.click(screen.getByRole('button', { name: 'Cytowanie 1' }))
    expect(api.preview).toBe(0)
    await user.click(await screen.findByRole('button', { name: 'Otwórz dokument' }))

    expect(await screen.findByText('Smok wawelski mieszkał w jaskini.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Smok.pdf' })).toBeInTheDocument()
    await waitFor(() => expect(api.preview).toBe(1))
  })

  it('👍 wysyła opinię o wiadomości, a „Wygeneruj ponownie” powtarza pytanie', async () => {
    const api = useWorkspaceApi(() => citationSession())
    const user = userEvent.setup()

    await renderWorkspace('s1')
    await user.click(await screen.findByRole('button', { name: 'Odpowiedź pomocna' }))
    await waitFor(() => expect(api.feedback).toEqual([{ thumbup: true, feedback: null }]))

    await user.click(await screen.findByRole('button', { name: 'Wygeneruj ponownie' }))
    await waitFor(() => expect(api.completions).toHaveLength(1))
    expect(api.completions[0]).toMatchObject({ question: 'Kim jest smok?', session_id: 's1' })
  })

  it('zębatka otwiera szufladę ustawień, a Anuluj ją zamyka', async () => {
    useWorkspaceApi()
    const user = userEvent.setup()

    await renderWorkspace('s1')
    await user.click(screen.getByRole('button', { name: 'Ustawienia czatu' }))

    expect(await screen.findByRole('tab', { name: 'Asystent' })).toBeInTheDocument()
    expect(screen.getByLabelText('Opis')).toHaveValue('A helpful Assistant')

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    await waitFor(() => expect(screen.queryByRole('tab')).not.toBeInTheDocument())
  })

  it('brak czatu pokazuje komunikat o nieznalezieniu, inny błąd — komunikat ogólny', async () => {
    useWorkspaceApi()

    await renderWithProviders(
      <ChatWorkspacePage chatId="nie-ma-takiego" onConversationChange={vi.fn()} />,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie znaleziono czatu.')

    cleanup()
    server.use(
      http.get(apiUrl('/api/v1/chats/:chatId'), () =>
        HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 }),
      ),
    )
    await renderWithProviders(<ChatWorkspacePage chatId={CHAT_ID} onConversationChange={vi.fn()} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się wczytać czatu.')
  })
})
