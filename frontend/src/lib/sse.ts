import { createParser } from 'eventsource-parser'

export type SseReference = {
  total?: number
  chunks?: unknown[] | Record<string, unknown>
  doc_aggs?: unknown[]
}

export type SseData = {
  answer?: string
  reference?: SseReference
  final?: boolean
  id?: string
  session_id?: string
  start_to_think?: boolean
  end_to_think?: boolean
}

/** Ramka po zdekodowaniu JSON z linii `data:`. */
export type SseFrame = { code: number; message?: string; data: SseData | true | null }

// Linia `data:` z niepoprawnym JSON-em jest pomijana (kontrakt §1).
function parseFrame(raw: string): SseFrame | null {
  try {
    return JSON.parse(raw) as SseFrame
  } catch {
    return null
  }
}

/**
 * Czyta strumień SSE z odpowiedzi i zwraca kolejne ramki.
 * Przerwanie `signal` kończy generator bez wyjątku i zwalnia czytnik.
 */
export async function* readSse(res: Response, signal: AbortSignal): AsyncGenerator<SseFrame> {
  if (res.body === null) return

  const reader = res.body.getReader()
  if (signal.aborted) {
    await reader.cancel()
    return
  }

  const decoder = new TextDecoder()
  const frames: SseFrame[] = []
  const parser = createParser({
    onEvent: (event) => {
      const frame = parseFrame(event.data)
      if (frame !== null) frames.push(frame)
    },
  })

  // Przerwanie zwalnia czytnik; oczekujące `read()` kończy się wtedy jako `done`.
  const abort = () => {
    void reader.cancel()
  }
  signal.addEventListener('abort', abort)

  try {
    let chunk = await reader.read()
    while (!chunk.done) {
      parser.feed(decoder.decode(chunk.value, { stream: true }))
      for (const frame of frames.splice(0)) yield frame
      chunk = await reader.read()
    }
    if (!signal.aborted) {
      // Ostatnia linia bez `\n` nie jest domknięta: parser odpala event dopiero na pustej linii.
      parser.feed('\n\n')
      for (const frame of frames.splice(0)) yield frame
    }
  } finally {
    signal.removeEventListener('abort', abort)
    // Konsument, który przerwał iterację (`break`/`return`) albo rzucił wyjątek bez abortu, też
    // musi zwolnić czytnik; po strumieniu już zamkniętym `cancel()` jest bezkosztowe.
    void reader.cancel()
  }
}
