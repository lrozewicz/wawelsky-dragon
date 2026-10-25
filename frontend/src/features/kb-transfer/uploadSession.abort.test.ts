/**
 * Przerwanie wysyłki paczki (kontrakt WP E7-2 §5): `AbortSignal` wołającego w trakcie porcji,
 * w przerwie między próbami i w stanie `paused` oraz `cancel()` (abort + `deleteImport`).
 * Wznawianie po sieci i odświeżenie sesji: `uploadSession.resume.test.ts`.
 */

import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, failNextUpload, resetKbTransfer } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { clearAccessToken } from '../auth/tokenStore'

import { uploadPackage } from './uploadSession'
import type { UploadCallbacks, UploadSession, UploadStatus } from './uploadSession'
import type { DatasetImport } from './types'

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

describe('uploadPackage — przerwanie wysyłki', () => {
  it('przerwanie w trakcie czekania na ponowienie kończy wysyłkę błędem AbortError', async () => {
    vi.useFakeTimers()
    failNextUpload(1)
    const controller = new AbortController()
    const { seen, cb } = collect(controller.signal)
    const puts: string[] = []
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'PUT') puts.push(request.headers.get('Content-Range') ?? '')
    })

    const session = uploadPackage(makeFile(6), cb)
    // Porcja padła błędem sieci — jesteśmy w przerwie 1 s przed ponowieniem.
    await vi.advanceTimersByTimeAsync(0)
    expect(seen.statuses).toEqual(['uploading', 'resuming'])

    controller.abort()

    await expect(session.done).rejects.toMatchObject({ name: 'AbortError' })
    expect(puts).toEqual(['bytes 0-5/6'])
  })

  it('przerwanie w stanie wstrzymania (paused) kończy wysyłkę błędem AbortError', async () => {
    vi.useFakeTimers()
    failNextUpload(4)
    const controller = new AbortController()
    const { seen, cb } = collect(controller.signal)

    const session = uploadPackage(makeFile(6), cb)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(4000)
    expect(seen.statuses.at(-1)).toBe('paused')

    controller.abort()

    await expect(session.done).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('sygnał przerwany przed startem nie wysyła nic', async () => {
    const controller = new AbortController()
    controller.abort()
    const { seen, cb } = collect(controller.signal)

    const done = uploadPackage(makeFile(6), cb).done

    await expect(done).rejects.toMatchObject({ name: 'AbortError' })
    expect(seen.session).toBeNull()
    expect(seen.statuses).toEqual([])
  })

  it('cancel() przerywa wysyłkę i porzuca sesję importu', async () => {
    const controller = new AbortController()
    const { seen, cb } = collect(controller.signal)
    const deleted: string[] = []
    server.use(
      http.put(CHUNK_ROUTE, async () => {
        await new Promise((resolve) => setTimeout(resolve, 100))
        return HttpResponse.error()
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

  it('cancel() po zakończonej wysyłce nie porzuca sesji importu', async () => {
    const controller = new AbortController()
    const { cb } = collect(controller.signal)
    const deleted: string[] = []
    server.use(
      http.delete(DELETE_ROUTE, ({ params }) => {
        deleted.push(String(params.importId))
        return kbOk({ deleted: true })
      }),
    )

    const session = uploadPackage(makeFile(6), cb)
    await expect(session.done).resolves.toMatchObject({ state: 'ready' })

    await session.cancel()

    expect(deleted).toEqual([])
  })

  it('cancel() w porcji, która domknęła paczkę, nie kasuje sesji', async () => {
    const controller = new AbortController()
    const { cb } = collect(controller.signal)
    const deleted: string[] = []
    const cancels: Promise<void>[] = []
    let handle: UploadSession | null = null
    // „Anuluj” trafia w tę samą porcję, w której dotarła ostatnia część paczki.
    const withCancel: UploadCallbacks = {
      ...cb,
      onProgress: (received, total) => {
        cb.onProgress(received, total)
        if (handle !== null) cancels.push(handle.cancel())
      },
    }
    server.use(
      http.delete(DELETE_ROUTE, ({ params }) => {
        deleted.push(String(params.importId))
        return kbOk({ deleted: true })
      }),
    )

    handle = uploadPackage(makeFile(6), withCancel)

    await expect(handle.done).resolves.toMatchObject({ state: 'ready' })
    await Promise.all(cancels)
    expect(deleted).toEqual([])
  })
})
