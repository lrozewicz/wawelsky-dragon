/**
 * Wysyłka paczki porcjami (kontrakt WP E7-2 §5): kolejność i rozmiar porcji, błędy serwera
 * i przerwanie wysyłki. Testy jadą na handlerach MSW z T1 (K19 §3).
 * Wznawianie po błędzie sieci i odświeżenie sesji: `uploadSession.resume.test.ts`.
 */

import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, failNextUpload, KB_CHUNK_SIZE, resetKbTransfer } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { clearAccessToken } from '../auth/tokenStore'

import { UPLOAD_BACKOFF_MS, uploadPackage } from './uploadSession'
import type { UploadCallbacks, UploadStatus } from './uploadSession'
import type { DatasetImport } from './types'

const MIB = 1024 * 1024
const CHUNK_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId/content')
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

describe('uploadPackage — porcje', () => {
  it('przerwy po błędzie sieci to 1 s / 2 s / 4 s (kontrakt §5)', () => {
    // Literały, nie import stałej — inaczej zmiana wartości przechodzi niezauważona.
    expect(UPLOAD_BACKOFF_MS).toEqual([1000, 2000, 4000])
  })

  it('wysyła 20 MiB w trzech porcjach po 8 MiB i kończy sesję stanem ready', async () => {
    const ranges: (string | null)[] = []
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'PUT') ranges.push(request.headers.get('Content-Range'))
    })
    const file = makeFile(20 * MIB)
    const { seen, cb } = collect(new AbortController().signal)

    const result = await uploadPackage(file, cb).done

    expect(ranges).toEqual([
      'bytes 0-8388607/20971520',
      'bytes 8388608-16777215/20971520',
      'bytes 16777216-20971519/20971520',
    ])
    expect(seen.progress).toEqual([
      [KB_CHUNK_SIZE, file.size],
      [2 * KB_CHUNK_SIZE, file.size],
      [file.size, file.size],
    ])
    expect(seen.statuses).toEqual(['uploading'])
    expect(seen.session).toMatchObject({ state: 'uploading', received_bytes: 0 })
    expect(result).toMatchObject({ state: 'ready', received_bytes: file.size })
  })

  it('plik 0 B odrzuca wysyłkę kodem empty_file, bez ani jednego żądania', async () => {
    let posts = 0
    server.use(
      http.post(apiUrl('/api/wd/v1/dataset-imports'), () => {
        posts += 1
        return kbOk(null, 201)
      }),
    )
    const { seen, cb } = collect(new AbortController().signal)

    const done = uploadPackage(makeFile(0), cb).done

    await expect(done).rejects.toMatchObject({ code: 'empty_file' })
    expect(posts).toBe(0)
    expect(seen.session).toBeNull()
    expect(seen.statuses).toEqual([])
  })
})

describe('uploadPackage — błędy serwera i przerwanie', () => {
  it('409 offset_mismatch wznawia od details.received_bytes', async () => {
    const file = makeFile(6)
    const { seen, cb } = collect(new AbortController().signal)
    const starts: number[] = []
    let puts = 0

    server.use(
      http.put(CHUNK_ROUTE, ({ request }) => {
        puts += 1
        const range = parseRange(request.headers.get('Content-Range'))
        if (range === null) return kbError(400, 'validation_failed')
        starts.push(range[0])
        if (puts === 1) return kbError(409, 'offset_mismatch', { received_bytes: 4 })
        const base = seen.session
        if (base === null) return HttpResponse.error()
        return kbOk({ ...base, received_bytes: file.size, state: 'ready' })
      }),
    )

    const result = await uploadPackage(file, cb).done

    expect(starts).toEqual([0, 4])
    expect(seen.statuses).toEqual(['uploading'])
    expect(result).toMatchObject({ state: 'ready' })
  })

  it('offset_mismatch bez details.received_bytes przerywa wysyłkę', async () => {
    let puts = 0
    const { cb } = collect(new AbortController().signal)
    server.use(
      http.put(CHUNK_ROUTE, () => {
        puts += 1
        return kbError(409, 'offset_mismatch')
      }),
    )

    const done = uploadPackage(makeFile(6), cb).done

    await expect(done).rejects.toMatchObject({ code: 'offset_mismatch', httpStatus: 409 })
    expect(puts).toBe(1)
  })

  it('inny błąd WD (import_not_ready) kończy wysyłkę bez ponawiania', async () => {
    let puts = 0
    const { seen, cb } = collect(new AbortController().signal)
    server.use(
      http.put(CHUNK_ROUTE, () => {
        puts += 1
        return kbError(409, 'import_not_ready', { state: 'started' })
      }),
    )

    const done = uploadPackage(makeFile(6), cb).done

    await expect(done).rejects.toMatchObject({ code: 'import_not_ready', httpStatus: 409 })
    expect(puts).toBe(1)
    expect(seen.statuses).toEqual(['uploading'])
  })

  it('przerwanie sygnału w trakcie porcji odrzuca done błędem AbortError', async () => {
    const controller = new AbortController()
    const { cb } = collect(controller.signal)
    let puts = 0
    server.use(
      http.put(CHUNK_ROUTE, async () => {
        puts += 1
        await new Promise((resolve) => setTimeout(resolve, 100))
        return kbError(500, 'upstream_error')
      }),
    )

    const session = uploadPackage(makeFile(20 * MIB), cb)
    setTimeout(() => controller.abort(), 10)

    await expect(session.done).rejects.toMatchObject({ name: 'AbortError' })
    expect(puts).toBe(1) // druga porcja nie poszła
  })

  it('przerwanie po pierwszej porcji nie wysyła już nic', async () => {
    const controller = new AbortController()
    const { seen, cb } = collect(controller.signal)
    const puts: string[] = []
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'PUT') puts.push(request.headers.get('Content-Range') ?? '')
    })
    // Użytkownik wciska „Anuluj” po pierwszej porcji.
    const aborting: UploadCallbacks = {
      ...cb,
      onProgress: (received, total) => {
        cb.onProgress(received, total)
        controller.abort()
      },
    }

    const session = uploadPackage(makeFile(20 * MIB), aborting)

    await expect(session.done).rejects.toMatchObject({ name: 'AbortError' })
    expect(puts).toEqual(['bytes 0-8388607/20971520'])
    expect(seen.progress).toEqual([[KB_CHUNK_SIZE, 20 * MIB]])
  })

  it('cancel() przerywa wysyłkę i porzuca sesję importu', async () => {
    const controller = new AbortController()
    const { seen, cb } = collect(controller.signal)
    const deleted: string[] = []
    server.use(
      http.put(CHUNK_ROUTE, async () => {
        await new Promise((resolve) => setTimeout(resolve, 100))
        return kbError(500, 'upstream_error')
      }),
      http.delete(DELETE_ROUTE, ({ params }) => {
        deleted.push(String(params.importId))
        return kbOk({ deleted: true })
      }),
    )

    const session = uploadPackage(makeFile(6), cb)
    await vi.waitUntil(() => seen.session !== null)
    const importId = seen.session?.import_id

    await session.cancel()

    expect(deleted).toEqual([importId])
    await expect(session.done).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('czwarty błąd sieci wstrzymuje wysyłkę, a resume() kończy ją bez wyboru pliku', async () => {
    vi.useFakeTimers()
    failNextUpload(4)
    const { seen, cb } = collect(new AbortController().signal)

    const session = uploadPackage(makeFile(6), cb)

    // Trzy próby po 1 s, 2 s i 4 s (kontrakt §5) — po każdej udane odpytanie wraca do `uploading`.
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(4000)
    expect(seen.statuses).toEqual([
      'uploading',
      'resuming',
      'uploading',
      'resuming',
      'uploading',
      'resuming',
      'uploading',
      'paused',
    ])

    session.resume()
    await vi.advanceTimersByTimeAsync(0)
    await expect(session.done).resolves.toMatchObject({ state: 'ready' })
    expect(seen.statuses.at(-1)).toBe('uploading')
  })
})
