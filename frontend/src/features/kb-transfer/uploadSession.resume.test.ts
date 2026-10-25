/**
 * Wznawianie wysyłki paczki po błędzie sieci (kontrakt WP E7-2 §5, SC-E7-2-04 krok 3) oraz
 * odświeżenie sesji w trakcie porcji (MINOR po T1). Porcje i przerwanie: `uploadSession.test.ts`.
 */

import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  failNextUpload,
  KB_CHUNK_SIZE,
  makeAccessToken,
  resetKbTransfer,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { clearAccessToken, setAccessToken } from '../auth/tokenStore'

import { uploadPackage } from './uploadSession'
import type { UploadCallbacks, UploadSession, UploadStatus } from './uploadSession'
import type { DatasetImport } from './types'

const MIB = 1024 * 1024
const CHUNK_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId/content')
const IMPORT_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId')
const nowSeconds = (): number => Math.floor(Date.now() / 1000)

beforeEach(() => {
  resetKbTransfer()
})

afterEach(() => {
  clearAccessToken()
  vi.useRealTimers()
  server.events.removeAllListeners()
})

/** Plik o zadanym rozmiarze — treść nie ma znaczenia, liczą się bajty i `Content-Range`. */
function makeFile(sizeBytes: number, name = 'paczka.wdkb.zip'): File {
  return new File([new Uint8Array(sizeBytes)], name)
}

/** Zbiera wywołania zwrotne wysyłki; `session` wypełnia się po `createImport`. */
function collect(signal: AbortSignal) {
  const seen: {
    session: DatasetImport | null
    progress: [number, number][]
    statuses: UploadStatus[]
  } = { session: null, progress: [], statuses: [] }
  const cb: UploadCallbacks = {
    signal,
    onSession: (imp) => {
      seen.session = imp
    },
    onProgress: (received, total) => seen.progress.push([received, total]),
    onStatus: (status) => seen.statuses.push(status),
  }
  return { seen, cb }
}

function kbOk(data: unknown, status = 200): Response {
  return HttpResponse.json({ data }, { status })
}

function kbError(status: number, code: string, details?: Record<string, unknown>): Response {
  return HttpResponse.json(
    { error: details === undefined ? { code, message: code } : { code, message: code, details } },
    { status },
  )
}

/** `Content-Range: bytes <start>-<end>/<total>` → `[start, end, total]`. */
function parseRange(header: string | null): [number, number, number] | null {
  const match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(header ?? '')
  return match === null ? null : [Number(match[1]), Number(match[2]), Number(match[3])]
}

describe('uploadPackage — wznowienie po błędzie sieci', () => {
  it('błąd sieci w drugiej porcji wznawia od bajtów serwera, bez zdublowania pierwszej', async () => {
    const file = makeFile(20 * MIB)
    const { seen, cb } = collect(new AbortController().signal)
    const starts: number[] = []
    let received = 0
    let puts = 0

    /** Serwer porcji w pamięci testu: zapisuje bajty, a przy drugiej porcji gubi odpowiedź. */
    const chunkBody = (at: number): Response => {
      const base = seen.session
      if (base === null) return kbError(409, 'import_not_ready')
      return kbOk({ ...base, received_bytes: at, state: at === file.size ? 'ready' : 'uploading' })
    }
    server.use(
      http.put(CHUNK_ROUTE, ({ request }) => {
        puts += 1
        const range = parseRange(request.headers.get('Content-Range'))
        if (range === null) return kbError(400, 'validation_failed')
        starts.push(range[0])
        received = range[1] + 1
        // Porcja dotarła do serwera, ale odpowiedź przepadła — wznawiamy od `getImport`.
        if (puts === 2) return HttpResponse.error()
        return chunkBody(received)
      }),
      http.get(IMPORT_ROUTE, () => chunkBody(received)),
    )

    const session = uploadPackage(file, cb)
    const result = await session.done

    // Porcja, której odpowiedź przepadła, dotarła — żadna porcja nie leci drugi raz.
    expect(starts).toEqual([0, KB_CHUNK_SIZE, 2 * KB_CHUNK_SIZE])
    expect(seen.statuses).toEqual(['uploading', 'resuming', 'uploading'])
    expect(seen.progress).toEqual([
      [KB_CHUNK_SIZE, file.size],
      [file.size, file.size],
    ])
    expect(result).toMatchObject({ state: 'ready', received_bytes: file.size })
  })

  it('dłuższa przerwa sieci (padają też odpytania) kończy się wznowieniem bez pauzy', async () => {
    vi.useFakeTimers()
    const file = makeFile(6)
    const { seen, cb } = collect(new AbortController().signal)
    let puts = 0
    let gets = 0

    /** Odpowiedź serwera: ta sama sesja, stan odebranych bajtów wg `at`. */
    const chunkBody = (at: number): Response => {
      const base = seen.session
      if (base === null) return kbError(409, 'import_not_ready')
      return kbOk({ ...base, received_bytes: at, state: at === file.size ? 'ready' : 'uploading' })
    }

    server.use(
      http.put(CHUNK_ROUTE, ({ request }) => {
        puts += 1
        if (puts === 1) return HttpResponse.error() // sieć pada w trakcie pierwszej porcji
        const range = parseRange(request.headers.get('Content-Range'))
        if (range === null) return kbError(400, 'validation_failed')
        return chunkBody(range[1] + 1)
      }),
      http.get(IMPORT_ROUTE, () => {
        gets += 1
        // Pierwsze dwa odpytania wypadają w środku przerwy sieci (1 s i 3 s od jej początku).
        if (gets <= 2) return HttpResponse.error()
        return chunkBody(0)
      }),
    )

    const session = uploadPackage(file, cb)
    await vi.advanceTimersByTimeAsync(0)
    // Kontrakt §5: trzy przerwy 1 s, 2 s i 4 s.
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(4000)

    await expect(session.done).resolves.toMatchObject({ state: 'ready', received_bytes: file.size })
    expect(seen.statuses).toEqual(['uploading', 'resuming', 'resuming', 'resuming', 'uploading'])
    expect(puts).toBe(2)
    expect(gets).toBe(3)
  })

  it('utrata odpowiedzi ostatniej porcji daje wynik terminalny z serwera', async () => {
    const file = makeFile(6)
    const { seen, cb } = collect(new AbortController().signal)
    let puts = 0

    /** Jedna porcja: serwer ją zapisał i zwalidował, ale odpowiedź przepadła. */
    const chunkBody = (at: number): Response => {
      const base = seen.session
      if (base === null) return kbError(409, 'import_not_ready')
      return kbOk({ ...base, received_bytes: at, state: at === file.size ? 'ready' : 'uploading' })
    }
    server.use(
      http.put(CHUNK_ROUTE, () => {
        puts += 1
        return HttpResponse.error()
      }),
      http.get(IMPORT_ROUTE, () => chunkBody(file.size)),
    )

    const result = await uploadPackage(file, cb).done

    expect(result).toMatchObject({ state: 'ready', received_bytes: 6 })
    expect(puts).toBe(1) // porcja była kompletna — nie ma czego ponawiać
    expect(seen.progress).toEqual([[6, 6]]) // pasek dochodzi do 100%
  })

  it('offset_mismatch wskazujący na komplet daje wynik terminalny z serwera', async () => {
    const file = makeFile(6)
    const { seen, cb } = collect(new AbortController().signal)

    const chunkBody = (at: number): Response => {
      const base = seen.session
      if (base === null) return kbError(409, 'import_not_ready')
      return kbOk({ ...base, received_bytes: at, state: at === file.size ? 'ready' : 'uploading' })
    }
    server.use(
      http.put(CHUNK_ROUTE, () => kbError(409, 'offset_mismatch', { received_bytes: file.size })),
      http.get(IMPORT_ROUTE, () => chunkBody(file.size)),
    )

    const result = await uploadPackage(file, cb).done

    expect(result).toMatchObject({ state: 'ready', received_bytes: 6 })
    expect(seen.progress).toEqual([[6, 6]])
  })

  it('resume() wywołane w tym samym zdarzeniu co onStatus(paused) nie przepada', async () => {
    vi.useFakeTimers()
    failNextUpload(4)
    const { seen, cb } = collect(new AbortController().signal)
    let handle: UploadSession | null = null
    // UI, które wznawia natychmiast po pokazaniu stanu „Wznów”.
    const eager: UploadCallbacks = {
      ...cb,
      onStatus: (status) => {
        cb.onStatus(status)
        if (status === 'paused') handle?.resume()
      },
    }

    handle = uploadPackage(makeFile(6), eager)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(4000)

    await expect(handle.done).resolves.toMatchObject({ state: 'ready' })
    expect(seen.statuses).toContain('paused')
  })
})

describe('uploadPackage — odświeżenie sesji', () => {
  it('401 w trakcie porcji odświeża sesję i powtarza tę samą porcję (ciało przeżywa)', async () => {
    const stale = makeAccessToken(nowSeconds() + 900)
    const fresh = makeAccessToken(nowSeconds() + 1800)
    setAccessToken(stale)
    const authorizations: (string | null)[] = []
    const bodyLengths: number[] = []
    let puts = 0
    const { seen, cb } = collect(new AbortController().signal)

    server.use(
      http.put(CHUNK_ROUTE, async ({ request }) => {
        puts += 1
        authorizations.push(request.headers.get('Authorization'))
        bodyLengths.push((await request.arrayBuffer()).byteLength)
        if (puts === 1) return new HttpResponse(null, { status: 401 })
        const base = seen.session
        if (base === null) return HttpResponse.error()
        return kbOk({ ...base, received_bytes: 6, state: 'ready' })
      }),
      http.post(apiUrl('/api/v1/auth/refresh'), () =>
        HttpResponse.json({
          code: 0,
          message: 'success',
          data: { access_token: fresh, expires_in: 900 },
        }),
      ),
    )

    const result = await uploadPackage(makeFile(6), cb).done

    expect(puts).toBe(2)
    expect(bodyLengths).toEqual([6, 6])
    expect(authorizations).toEqual([`Bearer ${stale}`, `Bearer ${fresh}`])
    expect(result).toMatchObject({ state: 'ready' })
  })
})
