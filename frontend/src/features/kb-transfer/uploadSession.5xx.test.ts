/**
 * Wstrzymanie wysyłki po odpowiedzi 5xx serwera (kontrakt WP E67-z1a §C1, SC-E67-03):
 * bez automatycznych ponowień — `onStatus('paused', kod)` i czekanie na `resume()`, po którym
 * offset bierzemy z `getImport`. Regresja błędu sieci (`TypeError`): `paused` bez kodu.
 * Porcje: `uploadSession.test.ts`, wznowienie po sieci: `uploadSession.resume.test.ts`.
 */

import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, failNextUpload, KB_CHUNK_SIZE, resetKbTransfer } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { clearAccessToken } from '../auth/tokenStore'

import { uploadPackage } from './uploadSession'
import type { UploadCallbacks, UploadStatus } from './uploadSession'
import type { DatasetImport } from './types'

const MIB = 1024 * 1024
const CHUNK_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId/content')
const CREATE_ROUTE = apiUrl('/api/wd/v1/dataset-imports')
const IMPORT_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId')
const DELETE_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId')

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

/** Zbiera wywołania zwrotne wysyłki wraz z kodem pauzy; `session` wypełnia się po `createImport`. */
function collect(signal: AbortSignal) {
  const seen: {
    session: DatasetImport | null
    progress: [number, number][]
    statuses: [UploadStatus, number | undefined][]
  } = { session: null, progress: [], statuses: [] }
  const cb: UploadCallbacks = {
    signal,
    onSession: (imp) => {
      seen.session = imp
    },
    onProgress: (received, total) => seen.progress.push([received, total]),
    onStatus: (status, pauseHttpStatus) => seen.statuses.push([status, pauseHttpStatus]),
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

/** Czy wysyłka wstrzymała się już z podanym kodem HTTP. */
function pausedWith(
  seen: { statuses: [UploadStatus, number | undefined][] },
  code: number,
): boolean {
  return seen.statuses.some(
    ([status, pauseHttpStatus]) => status === 'paused' && pauseHttpStatus === code,
  )
}

describe('uploadPackage — odpowiedź 5xx serwera (kontrakt E67-z1a §C1)', () => {
  it('503 na porcji wstrzymuje wysyłkę i wznawia ją od offsetu serwera', async () => {
    const file = makeFile(20 * MIB)
    const { seen, cb } = collect(new AbortController().signal)
    const starts: number[] = []
    let blip = true
    let received = 0

    /** Serwer porcji w pamięci testu: bez odpytań oddaje stan odebranych bajtów. */
    const chunkBody = (at: number): Response => {
      const base = seen.session
      if (base === null) return kbError(409, 'import_not_ready')
      return kbOk({ ...base, received_bytes: at, state: at === file.size ? 'ready' : 'uploading' })
    }
    server.use(
      http.put(CHUNK_ROUTE, ({ request }) => {
        const range = parseRange(request.headers.get('Content-Range'))
        if (range === null) return kbError(400, 'validation_failed')
        starts.push(range[0])
        // Druga porcja raz: serwer chwilowo niedostępny.
        if (blip && range[0] === KB_CHUNK_SIZE) {
          blip = false
          return kbError(503, 'upstream_error')
        }
        received = range[1] + 1
        return chunkBody(received)
      }),
      http.get(IMPORT_ROUTE, () => chunkBody(received)),
    )

    const session = uploadPackage(file, cb)
    await vi.waitUntil(() => pausedWith(seen, 503))

    expect(seen.statuses).toEqual([
      ['uploading', undefined],
      ['paused', 503],
    ])
    // Kontrakt §C1: bez automatycznych ponowień — porcja z 503 nie leci drugi raz przed resume().
    expect(starts).toEqual([0, KB_CHUNK_SIZE])

    session.resume()
    const result = await session.done

    // Wznowienie od `received_bytes` serwera, potem dopiero trzecia porcja.
    expect(starts).toEqual([0, KB_CHUNK_SIZE, KB_CHUNK_SIZE, 2 * KB_CHUNK_SIZE])
    expect(seen.progress.at(-1)).toEqual([file.size, file.size])
    expect(result).toMatchObject({ state: 'ready', received_bytes: file.size })
  })

  it('5xx na odpytaniu po resume() wstrzymuje ponownie z nowym kodem', async () => {
    const file = makeFile(20 * MIB)
    const { seen, cb } = collect(new AbortController().signal)
    let blip = true
    let gets = 0
    let received = 0

    const chunkBody = (at: number): Response => {
      const base = seen.session
      if (base === null) return kbError(409, 'import_not_ready')
      return kbOk({ ...base, received_bytes: at, state: at === file.size ? 'ready' : 'uploading' })
    }
    server.use(
      http.put(CHUNK_ROUTE, ({ request }) => {
        const range = parseRange(request.headers.get('Content-Range'))
        if (range === null) return kbError(400, 'validation_failed')
        if (blip && range[0] === KB_CHUNK_SIZE) {
          blip = false
          return kbError(503, 'upstream_error')
        }
        received = range[1] + 1
        return chunkBody(received)
      }),
      http.get(IMPORT_ROUTE, () => {
        gets += 1
        // Pierwsze odpytanie (po resume) trafia na bramę, która jeszcze nie wstała.
        if (gets === 1) return kbError(502, 'bad_gateway')
        return chunkBody(received)
      }),
    )

    const session = uploadPackage(file, cb)
    await vi.waitUntil(() => pausedWith(seen, 503))

    session.resume()
    await vi.waitUntil(() => pausedWith(seen, 502))

    // Bez `uploading` między pauzami: offset wracał z nieudanego odpytania.
    expect(seen.statuses).toEqual([
      ['uploading', undefined],
      ['paused', 503],
      ['paused', 502],
    ])

    session.resume()
    await expect(session.done).resolves.toMatchObject({ state: 'ready', received_bytes: file.size })
    expect(gets).toBe(2)
  })

  it('cancel() w stanie paused porzuca sesję importu', async () => {
    const { seen, cb } = collect(new AbortController().signal)
    const deleted: string[] = []
    server.use(
      http.put(CHUNK_ROUTE, () => kbError(503, 'upstream_error')),
      http.delete(DELETE_ROUTE, ({ params }) => {
        deleted.push(String(params.importId))
        return kbOk({ deleted: true })
      }),
    )

    const session = uploadPackage(makeFile(6), cb)
    await vi.waitUntil(() => pausedWith(seen, 503))

    await session.cancel()

    expect(deleted).toEqual([seen.session?.import_id])
    await expect(session.done).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('cancel() po rozstrzygniętym done nie kasuje sesji (flaga settled)', async () => {
    const { seen, cb } = collect(new AbortController().signal)
    const deleted: string[] = []
    server.use(
      // Sesja zakłada się z kompletem bajtów: pętla porcji nie rusza, więc `completed` zostaje
      // fałszem i tylko flaga `settled` powstrzymuje `cancel()` przed skasowaniem sesji.
      http.post(CREATE_ROUTE, () =>
        kbOk(
          {
            import_id: 'import-complete',
            file_name: 'paczka.wdkb.zip',
            size_bytes: 6,
            received_bytes: 6,
            chunk_size: KB_CHUNK_SIZE,
            state: 'ready',
            errors: [],
            summary: null,
            task_id: null,
            expires_at: Date.now() + 60_000,
          },
          201,
        ),
      ),
      http.delete(DELETE_ROUTE, ({ params }) => {
        deleted.push(String(params.importId))
        return kbOk({ deleted: true })
      }),
    )

    const session = uploadPackage(makeFile(6), cb)
    await expect(session.done).resolves.toMatchObject({ state: 'ready', received_bytes: 6 })

    expect(seen.progress, 'żadnej porcji nie było — pętla wysyłki nie ruszyła').toEqual([])

    await session.cancel()

    expect(deleted, 'sesja rozstrzygnięta sukcesem nie jest porzucana').toEqual([])
  })

  it('błąd sieci nadal daje resuming i paused bez kodu (regresja)', async () => {
    vi.useFakeTimers()
    failNextUpload(4)
    const { seen, cb } = collect(new AbortController().signal)

    const session = uploadPackage(makeFile(6), cb)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(4000)

    // Kontrakt §5 bez zmian: po błędzie sieci `resuming` z backoffem, na końcu `paused` — i to
    // bez kodu HTTP (kod ma tylko pauza po odpowiedzi 5xx).
    expect(seen.statuses.map(([status]) => status)).toEqual([
      'uploading',
      'resuming',
      'uploading',
      'resuming',
      'uploading',
      'resuming',
      'uploading',
      'paused',
    ])
    expect(seen.statuses.every(([, pauseHttpStatus]) => pauseHttpStatus === undefined)).toBe(true)

    session.resume()
    await vi.advanceTimersByTimeAsync(1000)

    await expect(session.done).resolves.toMatchObject({ state: 'ready', received_bytes: 6 })
  })
})
