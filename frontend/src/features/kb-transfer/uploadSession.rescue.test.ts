/**
 * Ścieżki ratunkowe wysyłki paczki (MINOR T2 z MINORS.md E7-2): `cancel()` po rozstrzygniętym
 * `done` nie kasuje kompletnej sesji (`completed` przed `accept`), a odpytanie stanu serwera
 * w gałęzi `offset_mismatch` podlega backoffowi sieci. Porcje i wznawianie: `uploadSession
 * .{test,resume}.test.ts`.
 */

import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiUrl, resetKbTransfer } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import { uploadPackage } from './uploadSession'
import type { UploadCallbacks, UploadStatus } from './uploadSession'
import type { DatasetImport } from './types'

const CHUNK_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId/content')
const IMPORT_ROUTE = apiUrl('/api/wd/v1/dataset-imports/:importId')

beforeEach(() => {
  resetKbTransfer()
})

afterEach(() => {
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

describe('uploadPackage — ścieżki ratunkowe (MINOR T2)', () => {
  it('cancel() po utracie odpowiedzi ostatniej porcji nie kasuje kompletnej sesji', async () => {
    const file = makeFile(6)
    const { seen, cb } = collect(new AbortController().signal)
    const deleted: string[] = []

    /** Jedna porcja: serwer ją zapisał i zwalidował, ale odpowiedź przepadła. */
    const chunkBody = (at: number): Response => {
      const base = seen.session
      if (base === null) return kbError(409, 'import_not_ready')
      return kbOk({ ...base, received_bytes: at, state: at === file.size ? 'ready' : 'uploading' })
    }
    server.use(
      http.put(CHUNK_ROUTE, () => HttpResponse.error()),
      http.get(IMPORT_ROUTE, () => chunkBody(file.size)),
      http.delete(IMPORT_ROUTE, ({ params }) => {
        deleted.push(String(params.importId))
        return kbOk({ deleted: true })
      }),
    )

    const session = uploadPackage(file, cb)
    await expect(session.done).resolves.toMatchObject({ state: 'ready' })
    await session.cancel()

    expect(deleted, 'sesja z kompletem nie jest porzucana').toEqual([])
  })

  it('cancel() po offset_mismatch z kompletem na serwerze nie kasuje sesji', async () => {
    const file = makeFile(6)
    const { seen, cb } = collect(new AbortController().signal)
    const deleted: string[] = []

    const chunkBody = (at: number): Response => {
      const base = seen.session
      if (base === null) return kbError(409, 'import_not_ready')
      return kbOk({ ...base, received_bytes: at, state: at === file.size ? 'ready' : 'uploading' })
    }
    server.use(
      http.put(CHUNK_ROUTE, () => kbError(409, 'offset_mismatch', { received_bytes: file.size })),
      http.get(IMPORT_ROUTE, () => chunkBody(file.size)),
      http.delete(IMPORT_ROUTE, ({ params }) => {
        deleted.push(String(params.importId))
        return kbOk({ deleted: true })
      }),
    )

    const session = uploadPackage(file, cb)
    await expect(session.done).resolves.toMatchObject({ state: 'ready' })
    await session.cancel()

    expect(deleted, 'sesja z kompletem nie jest porzucana').toEqual([])
  })

  it('odpytanie stanu po offset_mismatch podlega backoffowi sieci', async () => {
    vi.useFakeTimers()
    const file = makeFile(6)
    const { seen, cb } = collect(new AbortController().signal)
    let gets = 0

    const chunkBody = (at: number): Response => {
      const base = seen.session
      if (base === null) return kbError(409, 'import_not_ready')
      return kbOk({ ...base, received_bytes: at, state: at === file.size ? 'ready' : 'uploading' })
    }
    server.use(
      http.put(CHUNK_ROUTE, () => kbError(409, 'offset_mismatch', { received_bytes: file.size })),
      http.get(IMPORT_ROUTE, () => {
        gets += 1
        // Sieć pada dokładnie przy odpytaniu stanu — pierwsza próba przepada, druga idzie
        // z backoffem 1 s i kończy wysyłkę.
        if (gets === 1) return HttpResponse.error()
        return chunkBody(file.size)
      }),
    )

    const session = uploadPackage(file, cb)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1000)

    await expect(session.done).resolves.toMatchObject({ state: 'ready', received_bytes: 6 })
    expect(seen.statuses).toEqual(['uploading', 'resuming', 'uploading'])
    expect(gets).toBe(2)
  })
})
