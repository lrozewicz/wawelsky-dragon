/**
 * Klient REST eksportu/importu bazy wiedzy (kontrakt WP E7-2 §3, trasy 1–10 z K19 §3).
 * Trasy 5 (pobranie paczki) nie ma tutaj — to zwykły link `download_url` z atrybutem
 * `download` w `TaskRow` (strumieniowanie przez przeglądarkę, bez blobu w pamięci strony).
 * Trasy K19 nie ma jeszcze w `schema.gen.ts` (backend E7-1 w toku), dlatego wołamy klienta `api`
 * bez typów ścieżek — dzięki temu dostajemy jego middleware: Bearer z `tokenStore`,
 * `Accept-Language` oraz jedno wspólne odświeżenie sesji przy 401 z powtórzeniem żądania
 * (`uploadChunk` wysyła surowe bajty z `Content-Range`, więc korzysta z tego samego klienta).
 * Kopertę WD (`{data}` / `{error:{code,message,details}}`) rozpakowuje `wdCall`.
 */

import { api } from '../../api/client'
import { wdCall } from '../admin/wdClient'

import type { DatasetImport, ExportPreview, TaskRef, WdTask } from './types'

/** Wynik `openapi-fetch`: ciało w `data`/`error`, status w `response`. */
type RawResult = { data?: unknown; error?: unknown; response: Response }
type RawRequest = (path: string, init?: Record<string, unknown>) => Promise<RawResult>

/** Klient `api` bez typów ścieżek — trasy K19 są poza `schema.gen.ts`, middleware zostaje ten sam. */
const raw = api as unknown as {
  GET: RawRequest
  POST: RawRequest
  PUT: RawRequest
  DELETE: RawRequest
}

const BASE = '/api/wd/v1'

function datasetPath(datasetId: string): string {
  return `${BASE}/datasets/${encodeURIComponent(datasetId)}`
}

/** Trasa 1: `GET /datasets/{dataset_id}/export/preview`. */
export function previewExport(datasetId: string): Promise<ExportPreview> {
  return wdCall<ExportPreview>(raw.GET(`${datasetPath(datasetId)}/export/preview`))
}

/**
 * Trasa 2: `POST /datasets/{dataset_id}/export`. Gdy eksport tego datasetu już trwa, backend
 * odpowiada 409 `export_in_progress`, a jego `task_id` jest w `WdApiError.details`.
 */
export function startExport(datasetId: string, includeVectors: boolean): Promise<TaskRef> {
  return wdCall<TaskRef>(
    raw.POST(`${datasetPath(datasetId)}/export`, { body: { include_vectors: includeVectors } }),
  )
}

/** Trasa 3: `GET /tasks/{task_id}` — stan zadania dla paska zadań. */
export function getTask(taskId: string): Promise<WdTask> {
  return wdCall<WdTask>(raw.GET(`${BASE}/tasks/${encodeURIComponent(taskId)}`))
}

/** Trasa 4: `POST /tasks/{task_id}/stop` — `stopped=false`, gdy zadanie już się skończyło. */
export function stopTask(taskId: string): Promise<{ stopped: boolean }> {
  return wdCall<{ stopped: boolean }>(raw.POST(`${BASE}/tasks/${encodeURIComponent(taskId)}/stop`))
}

/** Trasa 6: `POST /dataset-imports` — zakłada sesję wysyłki paczki. */
export function createImport(fileName: string, sizeBytes: number): Promise<DatasetImport> {
  return wdCall<DatasetImport>(
    raw.POST(`${BASE}/dataset-imports`, { body: { file_name: fileName, size_bytes: sizeBytes } }),
  )
}

/**
 * Trasa 7: `PUT /dataset-imports/{import_id}/content` — porcja paczki jako surowe bajty
 * (`Content-Range: bytes <start>-<end>/<total>`). `start` musi równać się `received_bytes`,
 * inaczej 409 `offset_mismatch` z `details.received_bytes`.
 */
export async function uploadChunk(
  importId: string,
  start: number,
  total: number,
  bytes: Blob,
  signal?: AbortSignal,
): Promise<DatasetImport> {
  // Porcja ma ≤ `chunk_size` (8 MiB), więc czytamy ją do `ArrayBuffer`: to ciało zrozumiałe dla
  // każdej implementacji `Request` (przeglądarka i undici w vitest — jsdomowy `Blob` wywraca
  // konstrukcję `Request`). Bajty zostają te same, pozycję niesie `Content-Range`.
  const body = await bytes.arrayBuffer()
  return wdCall<DatasetImport>(
    raw.PUT(`${BASE}/dataset-imports/${encodeURIComponent(importId)}/content`, {
      body,
      // Surowe bajty — bez `JSON.stringify` (domyślnego serializatora klienta).
      bodySerializer: (payload: unknown) => payload,
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Range': `bytes ${start}-${start + body.byteLength - 1}/${total}`,
      },
      signal,
    }),
  )
}

/** Trasa 8: `GET /dataset-imports/{import_id}` — stan sesji (wznowienie od `received_bytes`). */
export function getImport(importId: string): Promise<DatasetImport> {
  return wdCall<DatasetImport>(raw.GET(`${BASE}/dataset-imports/${encodeURIComponent(importId)}`))
}

/**
 * Trasa 9: `POST /dataset-imports/{import_id}/start`. Zajęta nazwa → 409 `name_conflict`
 * z `details.suggested_name`; `embedding_model=null` znaczy „model domyślny aktora”.
 */
export function startImport(
  importId: string,
  name: string,
  embeddingModel: string | null,
): Promise<TaskRef> {
  return wdCall<TaskRef>(
    raw.POST(`${BASE}/dataset-imports/${encodeURIComponent(importId)}/start`, {
      body: { name, embedding_model: embeddingModel },
    }),
  )
}

/** Trasa 10: `DELETE /dataset-imports/{import_id}` — porzucenie sesji (także przy anulowaniu). */
export function deleteImport(importId: string): Promise<{ deleted: boolean }> {
  return wdCall<{ deleted: boolean }>(
    raw.DELETE(`${BASE}/dataset-imports/${encodeURIComponent(importId)}`),
  )
}
