import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { sessionKeys } from '../sessions/sessionQueries'

import { useChatStream } from './useChatStream'
import type { UseChatStream } from './useChatStream'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const CHAT_ID = 'chat-1'
const COMPLETIONS_URL = apiUrl(`/api/v1/chats/${CHAT_ID}/completions`)
const SSE_HEADERS = { 'Content-Type': 'text/event-stream; charset=utf-8' }

// Ramki w kształcie K4 §1.2 (kolejność kluczy jak w złocie; kodowanie `data:{json}\n\n` bez spacji).
const DELTA_TAIL = {
  reference: { chunks: [] },
  audio_binary: null,
  final: false,
  id: 'm1',
  session_id: 's1',
  chat_id: CHAT_ID,
}

function frame(data: unknown): string {
  return `data:${JSON.stringify({ code: 0, message: '', data })}\n\n`
}

/** AnswerDelta(t) — ten sam kształt co ThinkDelta(t). */
function delta(answer: string): string {
  return frame({ answer, ...DELTA_TAIL })
}

const FINAL = frame({
  answer: '',
  reference: { total: 0, chunks: [], doc_aggs: [] },
  prompt: '',
  created_at: 1.5,
  final: true,
  audio_binary: null,
  id: 'm1',
  session_id: 's1',
  chat_id: CHAT_ID,
})
const DONE = frame(true)
const THINK_START = `data:{"code":0,"message":"","data":{"answer":"","reference":{"chunks":[]},"audio_binary":null,"final":false,"start_to_think":true,"id":"m1","session_id":"s1","chat_id":"${CHAT_ID}"}}\n\n`
const THINK_END = `data:{"code":0,"message":"","data":{"answer":"","reference":{"chunks":[]},"audio_binary":null,"final":false,"end_to_think":true,"id":"m1","session_id":"s1","chat_id":"${CHAT_ID}"}}\n\n`
const ERROR_FRAME =
  'data:{"code":500,"message":"boom","data":{"answer":"**ERROR**: boom","reference":[]}}\n\n'

function sseStream(chunks: string[], onCancel?: () => void): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
    cancel: onCancel,
  })
}

/** Strumień otwarty do końca testu — test decyduje, kiedy dołożyć kolejną ramkę. */
function openSse(onCancel?: () => void): {
  stream: ReadableStream<Uint8Array>
  push: (text: string) => void
} {
  const encoder = new TextEncoder()
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null
  const stream = new ReadableStream<Uint8Array>({
    start(next) {
      controller = next
    },
    cancel: onCancel,
  })
  return { stream, push: (text) => controller?.enqueue(encoder.encode(text)) }
}

function streamHandler(chunks: string[]): HttpHandler {
  return http.post(
    COMPLETIONS_URL,
    () => new HttpResponse(sseStream(chunks), { headers: SSE_HEADERS }),
  )
}

/** Wynik hooka wypisany w DOM — testy czytają go przez `text(…)`. */
function Harness({ onSessionId }: { onSessionId?: (id: string) => void }) {
  const stream: UseChatStream = useChatStream(
    CHAT_ID,
    onSessionId === undefined ? undefined : { onSessionId },
  )
  return (
    <div>
      <span data-testid="phase">{stream.phase}</span>
      <span data-testid="answer">{stream.state.answer}</span>
      <span data-testid="thinking">{stream.state.thinking}</span>
      <span data-testid="error">{stream.state.error ?? ''}</span>
      <span data-testid="question">{stream.question ?? ''}</span>
      <button onClick={() => void stream.send('Pytanie', null)}>send</button>
      <button onClick={() => void stream.send('Drugie', null)}>send2</button>
      <button onClick={stream.stop}>stop</button>
      <button onClick={stream.reset}>reset</button>
    </div>
  )
}

async function renderStream(onSessionId?: (id: string) => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  })
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
  const result = await renderWithProviders(<Harness onSessionId={onSessionId} />, { queryClient })
  return { invalidate, unmount: result.unmount }
}

async function click(name: string): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name }))
  })
}

function text(testId: string): string {
  return screen.getByTestId(testId).textContent ?? ''
}

describe('useChatStream', () => {
  it('składa answer z ramki rozciętej w połowie, kończy done i unieważnia sesje', async () => {
    const first = delta('Ab')
    const cut = Math.floor(first.length / 2)
    server.use(streamHandler([first.slice(0, cut), first.slice(cut) + delta('c'), FINAL, DONE]))
    const { invalidate } = await renderStream()

    await click('send')
    await waitFor(() => expect(text('phase')).toBe('done'))

    expect(text('answer')).toBe('Abc')
    expect(text('question')).toBe('Pytanie')
    expect(invalidate).toHaveBeenCalledWith({ queryKey: sessionKeys.all(CHAT_ID) })
  })

  it('zbiera przyrost thinking z ramek think i nie miesza go z answer', async () => {
    server.use(streamHandler([THINK_START, delta('myślę'), THINK_END, delta('Odp'), FINAL, DONE]))
    await renderStream()

    await click('send')
    await waitFor(() => expect(text('phase')).toBe('done'))

    expect(text('thinking')).toBe('myślę')
    expect(text('answer')).toBe('Odp')
  })

  it('woła onSessionId raz, przy pierwszej ramce z session_id', async () => {
    const onSessionId = vi.fn()
    server.use(streamHandler([delta('A'), delta('B'), FINAL, DONE]))
    await renderStream(onSessionId)

    await click('send')
    await waitFor(() => expect(text('phase')).toBe('done'))

    expect(onSessionId).toHaveBeenCalledTimes(1)
    expect(onSessionId).toHaveBeenCalledWith('s1')
  })

  it('stop() przerywa strumień: faza aborted, częściowa odpowiedź zostaje', async () => {
    const open = openSse()
    server.use(
      http.post(COMPLETIONS_URL, () => new HttpResponse(open.stream, { headers: SSE_HEADERS })),
    )
    await renderStream()

    await click('send')
    open.push(delta('Ab'))
    await waitFor(() => expect(text('answer')).toBe('Ab'))

    await click('stop')

    await waitFor(() => expect(text('phase')).toBe('aborted'))
    expect(text('answer')).toBe('Ab')
    expect(text('error')).toBe('')
  })

  it('ramka code:500 kończy fazą error z komunikatem serwera', async () => {
    server.use(streamHandler([delta('Ab'), ERROR_FRAME, DONE]))
    await renderStream()

    await click('send')
    await waitFor(() => expect(text('phase')).toBe('error'))

    expect(text('error')).toBe('boom')
  })

  it('HTTP 500 kończy fazą error', async () => {
    server.use(
      http.post(COMPLETIONS_URL, () =>
        HttpResponse.json({ code: 500, message: 'boom', data: null }, { status: 500 }),
      ),
    )
    await renderStream()

    await click('send')
    await waitFor(() => expect(text('phase')).toBe('error'))

    expect(text('error')).toBe('HTTP 500')
  })

  it('błąd sieci kończy fazą error', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue('paf')
    await renderStream()

    await click('send')
    await waitFor(() => expect(text('phase')).toBe('error'))

    expect(text('error')).toBe('error')
  })

  it('send w trakcie streamu jest ignorowane', async () => {
    let requests = 0
    const open = openSse()
    server.use(
      http.post(COMPLETIONS_URL, () => {
        requests += 1
        return new HttpResponse(open.stream, { headers: SSE_HEADERS })
      }),
    )
    await renderStream()

    await click('send')
    await click('send2')
    open.push(delta('Ab'))
    await waitFor(() => expect(text('answer')).toBe('Ab'))

    expect(requests).toBe(1)
    expect(text('question')).toBe('Pytanie')
  })

  it('odmontowanie hooka przerywa strumień', async () => {
    let cancelled = false
    const open = openSse(() => {
      cancelled = true
    })
    // Podstawiony `fetch` (nie MSW): przechwycony strumień trafia do konsumenta bez kopii.
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(open.stream, { headers: SSE_HEADERS }))
    const { unmount } = await renderStream()

    await click('send')
    open.push(delta('Ab'))
    await waitFor(() => expect(text('answer')).toBe('Ab'))

    unmount()

    await waitFor(() => expect(cancelled).toBe(true))
    fetchSpy.mockRestore()
  })

  it('reset() wraca do stanu początkowego', async () => {
    const open = openSse()
    server.use(
      http.post(COMPLETIONS_URL, () => new HttpResponse(open.stream, { headers: SSE_HEADERS })),
    )
    await renderStream()

    await click('stop') // Stop bez trwającego streamu nic nie zmienia
    expect(text('phase')).toBe('idle')

    await click('send')
    open.push(delta('Ab'))
    await waitFor(() => expect(text('answer')).toBe('Ab'))

    await click('reset')

    await waitFor(() => expect(text('phase')).toBe('idle'))
    expect(text('answer')).toBe('')
    expect(text('question')).toBe('')
  })
})
