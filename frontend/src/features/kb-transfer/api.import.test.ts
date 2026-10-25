import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { apiUrl, KB_CHUNK_SIZE, resetKbTransfer, setImportPackage } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { clearAccessToken } from '../auth/tokenStore'

import { createImport, deleteImport, getImport, getTask, startImport, uploadChunk } from './api'
import type { DatasetImport } from './types'

beforeEach(() => {
  resetKbTransfer()
})

afterEach(() => {
  clearAccessToken()
})

/** Sesja importu zakończona walidacją paczki (`state=ready`) — wejście do trasy 9. */
async function readyImport(): Promise<DatasetImport> {
  const created = await createImport('paczka.wdkb.zip', 6)
  return uploadChunk(created.import_id, 0, 6, new Blob(['abcdef']))
}

/** Odpytuje zadanie importu aż do stanu końcowego i oddaje jego `result`. */
async function finishedImport(taskId: string) {
  let task = await getTask(taskId)
  for (let i = 0; i < 10 && task.status !== 'done'; i += 1) task = await getTask(taskId)
  return task.result
}

describe('createImport / uploadChunk', () => {
  it('nowa sesja importu ma rozmiar porcji z backendu (chunk_size)', async () => {
    const created = await createImport('Rocznik.zip', 1024)

    expect(created).toMatchObject({
      file_name: 'Rocznik.zip',
      size_bytes: 1024,
      received_bytes: 0,
      chunk_size: KB_CHUNK_SIZE,
      state: 'uploading',
      errors: [],
      summary: null,
    })
  })

  it('wysyła surowe bajty z nagłówkiem Content-Range, ostatnia porcja kończy walidację', async () => {
    const created = await createImport('paczka.wdkb.zip', 6)

    const done = await uploadChunk(created.import_id, 0, 6, new Blob(['abcdef']))

    expect(done).toMatchObject({ received_bytes: 6, state: 'ready' })
    expect(done.summary?.documents).toBe(3)
  })

  it('stawia nagłówek `Content-Range: bytes start-end/total` i nie serializuje ciała do JSON', async () => {
    const created = await createImport('paczka.wdkb.zip', 6)
    let contentRange: string | null = null
    let contentType: string | null = null
    let sent = ''
    server.use(
      http.put(apiUrl('/api/wd/v1/dataset-imports/:importId/content'), async ({ request }) => {
        contentRange = request.headers.get('Content-Range')
        contentType = request.headers.get('Content-Type')
        sent = await request.text()
        return HttpResponse.json({ data: { ...created, received_bytes: 6 } })
      }),
    )

    await uploadChunk(created.import_id, 0, 6, new Blob(['abcdef']))

    expect(contentRange).toBe('bytes 0-5/6')
    expect(contentType).toBe('application/octet-stream')
    expect(sent).toBe('abcdef')
  })

  it('porcja od złej pozycji daje 409 offset_mismatch z details.received_bytes', async () => {
    const created = await createImport('paczka.wdkb.zip', 12)
    await uploadChunk(created.import_id, 0, 12, new Blob(['abcdef']))

    await expect(uploadChunk(created.import_id, 0, 12, new Blob(['abcdef']))).rejects.toMatchObject(
      {
        code: 'offset_mismatch',
        httpStatus: 409,
        details: { received_bytes: 6 },
      },
    )
  })

  it('uszkodzona paczka kończy sesję stanem `invalid` z listą błędów', async () => {
    setImportPackage([
      { code: 'checksum_mismatch', message: 'Paczka uszkodzona (suma kontrolna).' },
    ])

    const created = await createImport('paczka.wdkb.zip', 6)
    const done = await uploadChunk(created.import_id, 0, 6, new Blob(['abcdef']))

    expect(done.state).toBe('invalid')
    expect(done.errors).toEqual([
      { code: 'checksum_mismatch', message: 'Paczka uszkodzona (suma kontrolna).' },
    ])
  })

  it('getImport oddaje stan sesji, nieznana sesja daje `not_found`', async () => {
    const created = await createImport('paczka.wdkb.zip', 6)

    await expect(getImport(created.import_id)).resolves.toMatchObject({ received_bytes: 0 })
    await expect(getImport('brak')).rejects.toMatchObject({ code: 'not_found' })
  })
})

describe('startImport / deleteImport', () => {
  it('start z nazwą wolną i modelem paczki daje zadanie bez przeliczania wektorów', async () => {
    const ready = await readyImport()

    const ref = await startImport(
      ready.import_id,
      'Rocznik GUS 2024 (kopia)',
      'text-embedding-3-small',
    )

    await expect(finishedImport(ref.task_id)).resolves.toMatchObject({
      dataset_name: 'Rocznik GUS 2024 (kopia)',
      reembedded: false,
    })
  })

  it('inny model niż w paczce oznacza ponowny embedding', async () => {
    const ready = await readyImport()

    const ref = await startImport(ready.import_id, 'Rocznik GUS 2024 (bge)', 'bge-m3')

    await expect(finishedImport(ref.task_id)).resolves.toMatchObject({ reembedded: true })
  })

  it('model null bierze model domyślny aktora', async () => {
    const ready = await readyImport()

    await expect(
      startImport(ready.import_id, 'Rocznik GUS 2024 (domyślny)', null),
    ).resolves.toMatchObject({ status: 'queued' })
  })

  it('zajęta nazwa daje 409 name_conflict z details.suggested_name', async () => {
    const ready = await readyImport()

    await expect(
      startImport(ready.import_id, 'Rocznik GUS 2024', 'text-embedding-3-small'),
    ).rejects.toMatchObject({
      code: 'name_conflict',
      httpStatus: 409,
      details: { suggested_name: 'Rocznik GUS 2024 (import 2026-10-13)' },
    })
  })

  it('nieznany model daje 400 embedding_model_unknown', async () => {
    const ready = await readyImport()

    await expect(startImport(ready.import_id, 'Kopia', 'nie-ma-takiego')).rejects.toMatchObject({
      code: 'embedding_model_unknown',
      httpStatus: 400,
    })
  })

  it('start przed ostatnią porcją daje 409 import_not_ready z details.state', async () => {
    const created = await createImport('paczka.wdkb.zip', 6)

    await expect(startImport(created.import_id, 'Kopia', null)).rejects.toMatchObject({
      code: 'import_not_ready',
      details: { state: 'uploading' },
    })
  })

  it('deleteImport usuwa sesję, drugie wywołanie daje `not_found`', async () => {
    const created = await createImport('paczka.wdkb.zip', 6)

    await expect(deleteImport(created.import_id)).resolves.toEqual({ deleted: true })
    await expect(deleteImport(created.import_id)).rejects.toMatchObject({ code: 'not_found' })
  })
})
