import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiUrl } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { useSearchSummary } from './useSearchSummary'
import type { UseSearchSummary } from './useSearchSummary'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const SEARCH_ID = 'search-1'
const COMPLETIONS_URL = apiUrl(`/api/v1/searches/${SEARCH_ID}/completions`)
const SSE_HEADERS = { 'Content-Type': 'text/event-stream; charset=utf-8' }

/** Ramka SSE w kopercie RAGFlow — kodowanie `data:{json}\n\n` bez spacji. */
function frame(data: unknown): string {
  return `data:${JSON.stringify({ code: 0, message: '', data })}\n\n`
}

function delta(answer: string): string {
  return frame({ answer, reference: {}, final: false })
}

const CHUNK = {
  id: 'chunk-1',
  content: 'Legenda o smoku wawelskim.',
  document_id: 'doc-1',
  document_name: 'ragflow_intro.txt',
  similarity: 0.85,
}

const FINAL = frame({
  answer: '',
  reference: { total: 1, chunks: [CHUNK], doc_aggs: [] },
  final: true,
})
const DONE = frame(true)
const ERROR_FRAME = 'data:{"code":500,"message":"boom","data":{"answer":"**ERROR**: boom"}}\n\n'

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
function Harness() {
  const summary: UseSearchSummary = useSearchSummary(SEARCH_ID)
  return (
    <div>
      <span data-testid="phase">{summary.phase}</span>
      <span data-testid="answer">{summary.state.answer}</span>
      <span data-testid="error">{summary.state.error ?? ''}</span>
      <span data-testid="citations">{String(summary.state.citations.length)}</span>
      <button onClick={() => void summary.start('Pierwsze')}>start</button>
      <button onClick={() => void summary.start('Drugie')}>start2</button>
      <button onClick={summary.stop}>stop</button>
      <button onClick={summary.reset}>reset</button>
    </div>
  )
}

async function click(name: string): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name }))
  })
}

function text(testId: string): string {
  return screen.getByTestId(testId).textContent ?? ''
}

describe('useSearchSummary', () => {
  it('składa odpowiedź, kończy done i zbiera cytowania (kontrakt §3, przykład 3)', async () => {
    server.use(streamHandler([delta('Odp [ID:0]'), FINAL, DONE]))
    await renderWithProviders(<Harness />)

    await click('start')
    await waitFor(() => expect(text('phase')).toBe('done'))

    expect(text('answer')).toBe('Odp [ID:0]')
    expect(text('citations')).toBe('1')
  })

  it('nowy start przerywa poprzedni strumień i czyści stan', async () => {
    let cancelled = false
    const first = openSse(() => {
      cancelled = true
    })
    const second = openSse()
    let calls = 0
    // Podstawiony `fetch` (nie MSW): przechwycony strumień trafia do konsumenta bez kopii.
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      calls += 1
      return Promise.resolve(
        new Response(calls === 1 ? first.stream : second.stream, { headers: SSE_HEADERS }),
      )
    })
    await renderWithProviders(<Harness />)

    await click('start')
    first.push(delta('Stare'))
    await waitFor(() => expect(text('answer')).toBe('Stare'))

    await click('start2')
    await waitFor(() => expect(cancelled).toBe(true))
    expect(text('phase')).toBe('streaming')
    expect(text('answer')).toBe('')

    second.push(delta('Nowe'))
    await waitFor(() => expect(text('answer')).toBe('Nowe'))
  })

  it('ramka code:500 kończy fazą error z komunikatem serwera', async () => {
    server.use(streamHandler([delta('Stare'), ERROR_FRAME, DONE]))
    await renderWithProviders(<Harness />)

    await click('start')
    await waitFor(() => expect(text('phase')).toBe('error'))

    expect(text('error')).toBe('boom')
  })

  it('HTTP 500 kończy fazą error', async () => {
    server.use(
      http.post(COMPLETIONS_URL, () =>
        HttpResponse.json({ code: 500, message: 'boom', data: null }, { status: 500 }),
      ),
    )
    await renderWithProviders(<Harness />)

    await click('start')
    await waitFor(() => expect(text('phase')).toBe('error'))

    expect(text('error')).toBe('HTTP 500')
  })

  it('stop() przerywa strumień, częściowa odpowiedź zostaje', async () => {
    const open = openSse()
    server.use(
      http.post(COMPLETIONS_URL, () => new HttpResponse(open.stream, { headers: SSE_HEADERS })),
    )
    await renderWithProviders(<Harness />)

    await click('start')
    open.push(delta('Stare'))
    await waitFor(() => expect(text('answer')).toBe('Stare'))

    await click('stop')

    await waitFor(() => expect(text('phase')).toBe('aborted'))
    expect(text('answer')).toBe('Stare')
  })

  it('odmontowanie hooka przerywa strumień', async () => {
    let cancelled = false
    const open = openSse(() => {
      cancelled = true
    })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(open.stream, { headers: SSE_HEADERS }),
    )
    const { unmount } = await renderWithProviders(<Harness />)

    await click('start')
    open.push(delta('Stare'))
    await waitFor(() => expect(text('answer')).toBe('Stare'))

    unmount()

    await waitFor(() => expect(cancelled).toBe(true))
  })

  it('reset() wraca do stanu początkowego', async () => {
    const open = openSse()
    server.use(
      http.post(COMPLETIONS_URL, () => new HttpResponse(open.stream, { headers: SSE_HEADERS })),
    )
    await renderWithProviders(<Harness />)

    await click('stop') // Stop bez trwającego strumienia nic nie zmienia
    expect(text('phase')).toBe('idle')

    await click('start')
    open.push(delta('Stare'))
    await waitFor(() => expect(text('answer')).toBe('Stare'))

    await click('reset')

    await waitFor(() => expect(text('phase')).toBe('idle'))
    expect(text('answer')).toBe('')
    expect(text('error')).toBe('')
    expect(text('citations')).toBe('0')
  })
})
