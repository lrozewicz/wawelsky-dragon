import { describe, expect, it } from 'vitest'

import { readSse, type SseFrame } from './sse'

// Ramki w kształcie golden `backend/tests/contract/golden/v0.27.2/chats___completions/completion--09.sse`
// (placeholdery `<ID:…>` z golden zamienione na zwykłe identyfikatory).
const FRAME_SEARCH =
  'data:{"code":0,"message":"","data":{"answer":"Sorry! No relevant content was found in the knowledge base!","reference":{"chunks":[]},"prompt":"","audio_binary":null,"final":false,"id":"id-3","session_id":"session-1","chat_id":"chat-1"}}\n\n'
const FRAME_ANSWER =
  'data:{"code":0,"message":"","data":{"answer":"Odpowiedź testowa","reference":{"total":1,"chunks":[],"doc_aggs":[]},"final":false,"id":"id-3","session_id":"session-1","chat_id":"chat-1"}}\n\n'
const FRAME_FINAL =
  'data:{"code":0,"message":"","data":{"answer":"Odpowiedź testowa: Output:","reference":{"total":0,"chunks":[],"doc_aggs":[]},"prompt":"\\n\\n### Query:\\nOdpowiedź testowa: Output:","audio_binary":null,"final":true,"id":"id-3","session_id":"session-1","chat_id":"chat-1"}}\n\n'
const FRAME_DONE = 'data:{"code":0,"message":"","data":true}\n\n'

// Strumień testowy wg briefu: `new Response(new ReadableStream({…}))` + TextEncoder.
function sseResponse(chunks: string[], onCancel?: () => void): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
      cancel: onCancel,
    }),
  )
}

async function collect(res: Response, signal?: AbortSignal): Promise<SseFrame[]> {
  const frames: SseFrame[] = []
  for await (const frame of readSse(res, signal ?? new AbortController().signal)) {
    frames.push(frame)
  }
  return frames
}

describe('readSse', () => {
  it('czyta trzy ramki i terminator data:true', async () => {
    const frames = await collect(sseResponse([FRAME_SEARCH, FRAME_ANSWER, FRAME_FINAL, FRAME_DONE]))
    expect(frames).toHaveLength(4)
    expect(frames.map((frame) => frame.code)).toEqual([0, 0, 0, 0])
    expect(frames.at(-2)).toMatchObject({
      data: { answer: 'Odpowiedź testowa: Output:', final: true, session_id: 'session-1' },
    })
    expect(frames.at(-1)?.data).toBe(true)
  })

  it('czyta data: ze spacją po dwukropku', async () => {
    const frames = await collect(
      sseResponse([FRAME_DONE.replace('data:', 'data: '), FRAME_SEARCH.replace('data:', 'data: ')]),
    )
    expect(frames).toHaveLength(2)
    expect(frames.at(-1)).toMatchObject({ data: { session_id: 'session-1' } })
  })

  it('czyta ramki zakończone CRLF', async () => {
    const frames = await collect(
      sseResponse([`${FRAME_FINAL.trimEnd()}\r\n\r\n${FRAME_DONE.trimEnd()}\r\n\r\n`]),
    )
    expect(frames).toHaveLength(2)
    expect(frames.at(0)).toMatchObject({ data: { final: true } })
    expect(frames.at(-1)?.data).toBe(true)
  })

  it('składa ramkę rozciętą w środku JSON między chunkami', async () => {
    const frames = await collect(
      sseResponse(['data:{"code":0,"message":"","da', 'ta":{"answer":"dwie części"}}\n\n']),
    )
    expect(frames).toEqual([{ code: 0, message: '', data: { answer: 'dwie części' } }])
  })

  it('nie gubi ostatniej ramki bez końcowego \\n', async () => {
    const last = 'data:{"code":0,"message":"","data":{"answer":"koniec"}}'
    const bezNewline = await collect(sseResponse([FRAME_SEARCH, last]))
    expect(bezNewline).toHaveLength(2)
    expect(bezNewline.at(-1)).toMatchObject({ data: { answer: 'koniec' } })

    const zJednymNewline = await collect(sseResponse([FRAME_SEARCH, `${last}\n`]))
    expect(zJednymNewline).toHaveLength(2)
    expect(zJednymNewline.at(-1)).toMatchObject({ data: { answer: 'koniec' } })
  })

  it('ignoruje komentarze oraz linie event: i id:', async () => {
    const frames = await collect(
      sseResponse([`: ping\nevent: message\nid: 1\n${FRAME_FINAL}event: message\n${FRAME_DONE}`]),
    )
    expect(frames).toHaveLength(2)
    expect(frames.at(0)).toMatchObject({ data: { session_id: 'session-1', final: true } })
    expect(frames.at(-1)?.data).toBe(true)
  })

  it('pomija ramkę z niepoprawnym JSON i czyta kolejną', async () => {
    const frames = await collect(sseResponse(['data:{nie-json}\n\n', FRAME_DONE]))
    expect(frames).toEqual([{ code: 0, message: '', data: true }])
  })

  it('kończy się bez wyjątku po przerwaniu signal i zwalnia czytnik', async () => {
    const encoder = new TextEncoder()
    const controller = new AbortController()
    let cancelled = false
    const res = new Response(
      new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(encoder.encode(FRAME_DONE))
        },
        cancel() {
          cancelled = true
        },
      }),
    )
    const frames: SseFrame[] = []
    for await (const frame of readSse(res, controller.signal)) {
      frames.push(frame)
      controller.abort()
    }
    expect(frames).toHaveLength(1)
    expect(cancelled).toBe(true)
  })

  it('zwalnia czytnik, gdy konsument przerwie iterację przez break', async () => {
    const encoder = new TextEncoder()
    let cancelled = false
    const res = new Response(
      new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(encoder.encode(FRAME_SEARCH))
          c.enqueue(encoder.encode(FRAME_DONE))
        },
        cancel() {
          cancelled = true
        },
      }),
    )

    const frames: SseFrame[] = []
    for await (const frame of readSse(res, new AbortController().signal)) {
      frames.push(frame)
      break
    }

    expect(frames).toHaveLength(1)
    expect(cancelled).toBe(true)
  })

  it('zwalnia czytnik, gdy konsument rzuci wyjątek bez abortu', async () => {
    const encoder = new TextEncoder()
    let cancelled = false
    const res = new Response(
      new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(encoder.encode(FRAME_SEARCH))
        },
        cancel() {
          cancelled = true
        },
      }),
    )

    await expect(
      (async () => {
        for await (const frame of readSse(res, new AbortController().signal)) {
          throw new Error(`konsument: ${frame.code}`)
        }
      })(),
    ).rejects.toThrow('konsument: 0')

    expect(cancelled).toBe(true)
  })

  it('kończy się od razu, gdy signal był przerwany przed startem', async () => {
    const controller = new AbortController()
    controller.abort()
    let cancelled = false
    const frames = await collect(
      sseResponse([FRAME_DONE], () => (cancelled = true)),
      controller.signal,
    )
    expect(frames).toEqual([])
    expect(cancelled).toBe(true)
  })

  it('zwraca pusty wynik, gdy odpowiedź nie ma ciała', async () => {
    expect(await collect(new Response(null))).toEqual([])
  })
})
