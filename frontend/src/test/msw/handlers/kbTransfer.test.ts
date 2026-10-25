import { beforeEach, describe, expect, it } from 'vitest'

import type { DatasetImport, ExportPreview, WdTask } from '../../../features/kb-transfer/types'
import { apiUrl } from './common'
import {
  failNextUpload,
  failTask,
  kbTransferHandlers,
  KB_DATASET_ID,
  KB_MAX_BYTES,
  resetKbTransfer,
  setExportForbidden,
  setExportPreview,
  setImportPackage,
  setTakenNames,
} from './kbTransfer'

/** Wołanie tras K19 §3 wprost przez `fetch` — testujemy handlery, nie klienta z `features`. */
function kbi(path: string, init?: RequestInit): Promise<Response> {
  return fetch(apiUrl(`/api/wd/v1${path}`), init)
}

function postJson(path: string, body: unknown): Promise<Response> {
  return kbi(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

async function envelope<T>(response: Response): Promise<T> {
  return ((await response.json()) as { data: T }).data
}

/** Ciało błędu w kopercie WD: `{"error": {code, message, details?}}` (K3 §3 p. 4). */
type ErrorBody = { code: string; message: string; details?: Record<string, unknown> }

async function errorBody(response: Response): Promise<ErrorBody> {
  return ((await response.json()) as { error: ErrorBody }).error
}

async function startExport(): Promise<{ task_id: string }> {
  const response = await postJson(`/datasets/${KB_DATASET_ID}/export`, { include_vectors: true })
  return envelope<{ task_id: string }>(response)
}

async function uploadContent(importId: string, body: string, range: string): Promise<Response> {
  return kbi(`/dataset-imports/${importId}/content`, {
    method: 'PUT',
    headers: { 'Content-Range': range, 'Content-Type': 'application/octet-stream' },
    body,
  })
}

/** Sesja importu po ostatniej porcji — `state` z wyniku walidacji (`ready` albo `invalid`). */
async function uploadedImport(size = 6): Promise<DatasetImport> {
  const created = await envelope<DatasetImport>(
    await postJson('/dataset-imports', { file_name: 'paczka.wdkb.zip', size_bytes: size }),
  )
  const response = await uploadContent(created.import_id, 'abcdef', `bytes 0-${size - 1}/${size}`)
  return envelope<DatasetImport>(response)
}

beforeEach(() => {
  resetKbTransfer()
})

describe('handlery MSW — eksport (K19 §3 trasy 1–5)', () => {
  it('preview oddaje podgląd z ziarna w kopercie `{data}`', async () => {
    const response = await kbi(`/datasets/${KB_DATASET_ID}/export/preview`)

    expect(response.status).toBe(200)
    const preview = await envelope<ExportPreview>(response)
    expect(preview).toMatchObject({ dataset_id: KB_DATASET_ID, documents: 3, chunks: 7251 })
    expect(preview.max_bytes).toBe(KB_MAX_BYTES)
  })

  it('`setExportPreview` podmienia podgląd, `null` daje 404', async () => {
    setExportPreview({
      ...(await envelope<ExportPreview>(await kbi(`/datasets/d1/export/preview`))),
      name: 'Umowy',
      dataset_id: 'd2',
    })

    const moved = await kbi('/datasets/d2/export/preview')
    expect((await envelope<ExportPreview>(moved)).name).toBe('Umowy')
    expect((await kbi('/datasets/d1/export/preview')).status).toBe(404)

    setExportPreview(null)
    const missing = await kbi('/datasets/d2/export/preview')
    expect(missing.status).toBe(404)
    expect((await errorBody(missing)).code).toBe('not_found')
  })

  it('`setExportForbidden` włącza 403 `forbidden` na trasach 1–2', async () => {
    setExportForbidden(true)

    const preview = await kbi(`/datasets/${KB_DATASET_ID}/export/preview`)
    const start = await postJson(`/datasets/${KB_DATASET_ID}/export`, {})

    expect(preview.status).toBe(403)
    expect((await errorBody(preview)).code).toBe('forbidden')
    expect(start.status).toBe(403)
  })

  it('start eksportu daje 202 i TaskRef, drugi raz 409 z `details.task_id`', async () => {
    const started = await postJson(`/datasets/${KB_DATASET_ID}/export`, { include_vectors: true })
    expect(started.status).toBe(202)
    const ref = await envelope<{ task_id: string; status: string }>(started)
    expect(ref.status).toBe('queued')

    const second = await postJson(`/datasets/${KB_DATASET_ID}/export`, { include_vectors: true })
    expect(second.status).toBe(409)
    const error = await errorBody(second)
    expect(error.code).toBe('export_in_progress')
    expect(error.details).toEqual({ task_id: ref.task_id })
  })

  it('szacunek powyżej limitu daje 413 `package_too_large`', async () => {
    const preview = await envelope<ExportPreview>(
      await kbi(`/datasets/${KB_DATASET_ID}/export/preview`),
    )
    setExportPreview({ ...preview, max_bytes: 1024 })

    const response = await postJson(`/datasets/${KB_DATASET_ID}/export`, { include_vectors: true })

    expect(response.status).toBe(413)
    expect((await errorBody(response)).code).toBe('package_too_large')
  })

  it('odpytywanie zadania przechodzi etapy eksportu i kończy się wynikiem z linkiem', async () => {
    const { task_id } = await startExport()
    const stages: (string | null)[] = []
    let task = await envelope<WdTask>(await kbi(`/tasks/${task_id}`))
    for (let i = 0; i < 10 && task.status !== 'done'; i += 1) {
      stages.push(task.stage)
      task = await envelope<WdTask>(await kbi(`/tasks/${task_id}`))
    }

    expect(stages).toEqual(['files', 'chunks', 'vectors', 'finalize'])
    expect(task.result).toMatchObject({
      file_name: 'rocznik-gus-2024.wdkb.zip',
      download_url: expect.stringContaining(`/exports/${task_id}/download`),
    })
  })

  it('`failTask` kończy zadanie statusem `failed` z komunikatem sluga', async () => {
    const { task_id } = await startExport()
    failTask(task_id, 'checksum_mismatch')

    const task = await envelope<WdTask>(await kbi(`/tasks/${task_id}`))

    expect(task.status).toBe('failed')
    expect(task.error).toEqual({
      code: 'checksum_mismatch',
      message: 'Paczka uszkodzona (suma kontrolna).',
    })
  })

  it('stop zatrzymuje zadanie i zwalnia dataset, drugi stop daje `stopped: false`', async () => {
    const { task_id } = await startExport()

    const first = await kbi(`/tasks/${task_id}/stop`, { method: 'POST' })
    expect(await envelope<{ stopped: boolean }>(first)).toEqual({ stopped: true })
    const second = await kbi(`/tasks/${task_id}/stop`, { method: 'POST' })
    expect(await envelope<{ stopped: boolean }>(second)).toEqual({ stopped: false })

    const again = await postJson(`/datasets/${KB_DATASET_ID}/export`, {})
    expect(again.status).toBe(202)
  })

  it('link pobrania wymaga podpisu, wygasły `exp` daje 410', async () => {
    const { task_id } = await startExport()
    const task = await kbi(`/tasks/${task_id}`)
    const downloadUrl = (await envelope<WdTask>(task)).result
    expect(downloadUrl).toBeNull() // wynik dochodzi dopiero po `done`

    const signed = await fetch(
      `${apiUrl(`/api/wd/v1/exports/${task_id}/download`)}?exp=9999999999&sig=x`,
    )
    expect(signed.status).toBe(200)
    expect(signed.headers.get('Content-Type')).toBe('application/zip')

    const unsigned = await kbi(`/exports/${task_id}/download?exp=9999999999`)
    expect(unsigned.status).toBe(403)
    expect((await errorBody(unsigned)).code).toBe('invalid_signature')

    const expired = await kbi(`/exports/${task_id}/download?exp=1&sig=x`)
    expect(expired.status).toBe(410)
    expect((await errorBody(expired)).code).toBe('export_expired')
  })

  it('nieznane zadanie i nieznana trasa zadań dają 404', async () => {
    expect((await kbi('/tasks/brak')).status).toBe(404)
    expect((await kbi('/tasks/brak/stop', { method: 'POST' })).status).toBe(404)
  })
})

describe('handlery MSW — import (K19 §3 trasy 6–10)', () => {
  it('sesja importu: 201 z rozmiarem porcji, złe ciało 400, za duży plik 413', async () => {
    const created = await postJson('/dataset-imports', {
      file_name: 'paczka.wdkb.zip',
      size_bytes: 6,
    })
    expect(created.status).toBe(201)
    expect(await envelope<DatasetImport>(created)).toMatchObject({
      received_bytes: 0,
      chunk_size: 8388608,
      state: 'uploading',
    })

    const bad = await postJson('/dataset-imports', { file_name: '', size_bytes: 0 })
    expect(bad.status).toBe(400)
    expect((await errorBody(bad)).code).toBe('validation_failed')

    const huge = await postJson('/dataset-imports', {
      file_name: 'paczka.wdkb.zip',
      size_bytes: KB_MAX_BYTES + 1,
    })
    expect(huge.status).toBe(413)
    expect((await errorBody(huge)).code).toBe('package_too_large')
  })

  it('porcja kończąca uruchamia walidację i oddaje podsumowanie paczki', async () => {
    const session = await uploadedImport()

    expect(session).toMatchObject({ received_bytes: 6, state: 'ready' })
    expect(session.summary?.name).toBe('Rocznik GUS 2024')
    expect(session.summary?.target.compatible).toBe(true)
  })

  it('`setImportPackage` z listą błędów kończy sesję stanem `invalid`', async () => {
    setImportPackage([{ code: 'schema_too_new', message: 'Paczka z nowszej wersji.' }])

    const session = await uploadedImport()

    expect(session.state).toBe('invalid')
    expect(session.errors).toEqual([
      { code: 'schema_too_new', message: 'Paczka z nowszej wersji.' },
    ])
    expect(session.summary).toBeNull()
  })

  it('zła porcja: brak nagłówka 400, nie ta pozycja 409 z `details.received_bytes`', async () => {
    const created = await envelope<DatasetImport>(
      await postJson('/dataset-imports', { file_name: 'paczka.wdkb.zip', size_bytes: 12 }),
    )

    const withoutHeader = await kbi(`/dataset-imports/${created.import_id}/content`, {
      method: 'PUT',
      body: 'abcdef',
    })
    expect(withoutHeader.status).toBe(400)
    expect((await errorBody(withoutHeader)).code).toBe('validation_failed')

    await uploadContent(created.import_id, 'abcdef', 'bytes 0-5/12')
    const late = await uploadContent(created.import_id, 'abcdef', 'bytes 0-5/12')
    expect(late.status).toBe(409)
    const error = await errorBody(late)
    expect(error.code).toBe('offset_mismatch')
    expect(error.details).toEqual({ received_bytes: 6 })
  })

  it('porcja po zakończeniu walidacji daje 409 `import_not_ready` ze stanem sesji', async () => {
    const session = await uploadedImport()

    const response = await uploadContent(session.import_id, 'abcd', 'bytes 0-3/6')

    expect(response.status).toBe(409)
    const error = await errorBody(response)
    expect(error.code).toBe('import_not_ready')
    expect(error.details).toEqual({ state: 'ready' })
  })

  it('`failNextUpload` zwraca błąd sieci (bez odpowiedzi HTTP)', async () => {
    const created = await envelope<DatasetImport>(
      await postJson('/dataset-imports', { file_name: 'paczka.wdkb.zip', size_bytes: 6 }),
    )
    failNextUpload(1)

    await expect(uploadContent(created.import_id, 'abcdef', 'bytes 0-5/6')).rejects.toThrow()

    const retry = await uploadContent(created.import_id, 'abcdef', 'bytes 0-5/6')
    expect(retry.status).toBe(200)
  })

  it('start importu: 202, zajęta nazwa 409 z `details.suggested_name`', async () => {
    const session = await uploadedImport()

    const conflict = await postJson(`/dataset-imports/${session.import_id}/start`, {
      name: 'Rocznik GUS 2024',
      embedding_model: 'text-embedding-3-small',
    })
    expect(conflict.status).toBe(409)
    const error = await errorBody(conflict)
    expect(error.code).toBe('name_conflict')
    expect(error.details).toEqual({ suggested_name: 'Rocznik GUS 2024 (import 2026-10-13)' })

    setTakenNames([])
    const started = await postJson(`/dataset-imports/${session.import_id}/start`, {
      name: 'Kopia',
      embedding_model: 'text-embedding-3-small',
    })
    expect(started.status).toBe(202)
    expect(await envelope<{ status: string }>(started)).toMatchObject({ status: 'queued' })
  })

  it('start bez modelu i bez modelu domyślnego daje 400 `embedding_model_required`', async () => {
    const session = await uploadedImport()
    setImportPackage({
      ...(session.summary as NonNullable<DatasetImport['summary']>),
      target: { compatible: false, default_model: null, models: [] },
    })
    const prepared = await uploadedImport()

    const response = await postJson(`/dataset-imports/${prepared.import_id}/start`, {
      name: 'Kopia',
      embedding_model: null,
    })

    expect(response.status).toBe(400)
    expect((await errorBody(response)).code).toBe('embedding_model_required')
  })

  it('zadanie importu przechodzi etapy z `documents` i `embedding`, potem `done`', async () => {
    setTakenNames([])
    const session = await uploadedImport()
    const ref = await envelope<{ task_id: string }>(
      await postJson(`/dataset-imports/${session.import_id}/start`, {
        name: 'Kopia',
        embedding_model: 'bge-m3',
      }),
    )

    const stages: (string | null)[] = []
    let task = await envelope<WdTask>(await kbi(`/tasks/${ref.task_id}`))
    for (let i = 0; i < 12 && task.status !== 'done'; i += 1) {
      stages.push(task.stage)
      task = await envelope<WdTask>(await kbi(`/tasks/${ref.task_id}`))
    }

    expect(stages).toEqual(['files', 'documents', 'chunks', 'vectors', 'embedding', 'finalize'])
    expect(task.result).toMatchObject({ dataset_name: 'Kopia', reembedded: true })
    // Start oznacza sesję jako `started` i podłącza zadanie.
    const after = await envelope<DatasetImport>(await kbi(`/dataset-imports/${session.import_id}`))
    expect(after).toMatchObject({ state: 'started', task_id: ref.task_id })
  })

  it('delete usuwa sesję (200 `{deleted:true}`), drugie wywołanie 404', async () => {
    const session = await uploadedImport()

    const first = await kbi(`/dataset-imports/${session.import_id}`, { method: 'DELETE' })
    expect(await envelope<{ deleted: boolean }>(first)).toEqual({ deleted: true })
    const second = await kbi(`/dataset-imports/${session.import_id}`, { method: 'DELETE' })
    expect(second.status).toBe(404)
  })
})

describe('resetKbTransfer', () => {
  it('czyści zadania, sesje importu i scenariusze', async () => {
    setExportForbidden(true)
    await startExport()
    resetKbTransfer()

    expect((await kbi(`/datasets/${KB_DATASET_ID}/export/preview`)).status).toBe(200)
    expect((await kbi('/dataset-imports/import-1')).status).toBe(404)
    expect((await postJson(`/datasets/${KB_DATASET_ID}/export`, {})).status).toBe(202)
  })

  it('handlery są dostępne przez wspólną listę `kbTransferHandlers()`', () => {
    expect(kbTransferHandlers().length).toBe(10)
  })
})
