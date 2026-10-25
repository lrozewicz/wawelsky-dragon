/**
 * Handlery MSW eksportu i importu bazy wiedzy (kontrakt WP E7-2 §1, trasy 1–10 z K19 §3).
 * Koperta WD: sukces `{data}`, błąd `{error:{code,message,details}}` ze statusami z K19.
 * Stan trzyma moduł (wzór `searches.ts`): każde wywołanie `kbTransferHandlers()` widzi ten sam
 * magazyn, a `resetKbTransfer()` wraca do ziarna — wołaj go w `beforeEach` testów tego obszaru.
 */

import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import type {
  DatasetImport,
  ExportPreview,
  ExportResult,
  ImportResult,
  ImportSummary,
  WdTask,
} from '../../../features/kb-transfer/types'
import { apiUrl } from './common'
import {
  KB_CHUNK_SIZE,
  KB_EXPORT_STAGES,
  KB_IMPORT_STAGES,
  KB_MAX_BYTES,
  KB_PACKAGE_MESSAGES,
  KB_STAGE_LABELS,
  KB_TTL_MS,
  kbDefaultPreview,
  kbDefaultSummary,
  kbSlug,
} from './kbTransferData'

// Eksporty wygody dla testów (wzór `admin.ts`) — stałe i ziarna z `./kbTransferData`.
export {
  KB_CHUNK_SIZE,
  KB_DATASET_ID,
  KB_MAX_BYTES,
  kbDefaultPreview,
  kbDefaultSummary,
} from './kbTransferData'

/** Błąd walidacji paczki widziany w `errors[]` i `WdTask.error`. */
type PackageError = { code: string; message: string }

interface MockTask {
  task: WdTask
  kind: 'export' | 'import'
  /** Liczba dotychczasowych odpytuń `GET /tasks/{id}` — postęp napędza odpytywanie. */
  step: number
  result: ExportResult | ImportResult
}

interface KbState {
  /** Podgląd eksportu bieżącego datasetu; `null` = dataset nie istnieje (404). */
  preview: ExportPreview | null
  /** `true` = trasy 1–2 zwracają 403 `forbidden` (K19 §Uprawnienia). */
  forbidden: boolean
  takenNames: string[]
  /** Ile kolejnych porcji uploadu padnie błędem sieci (`HttpResponse.error()`). */
  uploadFailures: number
  /** Wynik walidacji po ostatniej porcji: podsumowanie (`ready`) albo lista błędów (`invalid`). */
  packageOutcome: ImportSummary | PackageError[]
  tasks: Map<string, MockTask>
  imports: Map<string, DatasetImport>
  exportByDataset: Map<string, string>
  /** Kody błędów do podania przy najbliższym odpytaniu zadania (T4: wiersz „Błąd”). */
  failures: Map<string, string>
  seq: number
}

function initialState(): KbState {
  return {
    preview: kbDefaultPreview(),
    forbidden: false,
    takenNames: ['Rocznik GUS 2024'],
    uploadFailures: 0,
    packageOutcome: kbDefaultSummary(),
    tasks: new Map(),
    imports: new Map(),
    exportByDataset: new Map(),
    failures: new Map(),
    seq: 1,
  }
}

let state = initialState()

/** Przywraca magazyn do ziarna (domyślny dataset `d1`, brak zadań i sesji importu). */
export function resetKbTransfer(): void {
  state = initialState()
}

/** Podmienia podgląd eksportu (i tym samym identyfikator istniejącego datasetu); `null` = 404. */
export function setExportPreview(preview: ExportPreview | null): void {
  state.preview = preview
}

/** Włącza/wyłącza 403 `forbidden` na trasach 1–2. */
export function setExportForbidden(forbidden: boolean): void {
  state.forbidden = forbidden
}

/** Ustawia nazwy zajęte u aktora (409 `name_conflict` w trasie 9; porównanie bez wielkości liter). */
export function setTakenNames(names: string[]): void {
  state.takenNames = [...names]
}

/** Kolejne `times` porcji uploadu kończy się błędem sieci (bez odpowiedzi HTTP). */
export function failNextUpload(times: number): void {
  state.uploadFailures = times
}

/** Ustawia wynik walidacji paczki po ostatniej porcji: podsumowanie (`ready`) albo błędy (`invalid`). */
export function setImportPackage(next: ImportSummary | PackageError[]): void {
  state.packageOutcome = next
}

/** Najbliższe odpytanie zadania kończy je statusem `failed` z podanym kodem błędu. */
export function failTask(taskId: string, code: string): void {
  state.failures.set(taskId, code)
}

function wdOk(data: unknown, status = 200): Response {
  return HttpResponse.json({ data }, { status })
}

function wdError(
  status: number,
  code: string,
  message: string,
  details?: Record<string, unknown>,
): Response {
  return HttpResponse.json(
    { error: details ? { code, message, details } : { code, message } },
    {
      status,
    },
  )
}

function nextId(prefix: string): string {
  const id = `${prefix}${state.seq}`
  state.seq += 1
  return id
}

async function readJson(request: Request): Promise<Record<string, unknown>> {
  try {
    return (await request.json()) as Record<string, unknown>
  } catch {
    return {}
  }
}

function cloneSummary(summary: ImportSummary): ImportSummary {
  return {
    ...summary,
    embedding: { ...summary.embedding },
    target: { ...summary.target, models: summary.target.models.map((model) => ({ ...model })) },
  }
}

/** `Content-Range: bytes <start>-<end>/<total>` (K19 §3 trasa 7); niepoprawny → `null`. */
function parseContentRange(
  header: string | null,
): { start: number; end: number; total: number } | null {
  const match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(header ?? '')
  if (match === null) return null
  const start = Number(match[1])
  const end = Number(match[2])
  const total = Number(match[3])
  return end < start ? null : { start, end, total }
}

/** Wynik tras 1–2: podgląd datasetu albo gotowa odpowiedź błędu (403/404). */
type PreviewLookup = { preview: ExportPreview } | { error: Response }

/** Trasy 1–2: uprawnienia (403) i istnienie datasetu (404) przed zwróceniem podglądu. */
function lookupPreview(datasetId: string): PreviewLookup {
  if (state.forbidden) {
    return { error: wdError(403, 'forbidden', 'Brak uprawnień do tej bazy wiedzy.') }
  }
  const preview = state.preview
  if (preview === null || preview.dataset_id !== datasetId) {
    return { error: wdError(404, 'not_found', 'Nie znaleziono bazy wiedzy.') }
  }
  return { preview }
}

function isTakenName(name: string): boolean {
  return state.takenNames.some((taken) => taken.toLowerCase() === name.toLowerCase())
}

/** Zwalnia dataset po zakończeniu eksportu — kolejny `POST /export` nie da już 409. */
function releaseDataset(entry: MockTask): void {
  const datasetId = entry.task.dataset_id
  if (entry.kind === 'export' && datasetId !== null) state.exportByDataset.delete(datasetId)
}

/** Jedno odpytywanie zadania: kolejny etap, `failed` po `failTask`, na końcu `done` z wynikiem. */
function advance(entry: MockTask): WdTask {
  const { task } = entry
  if (task.status !== 'queued' && task.status !== 'running') return task

  const failure = state.failures.get(task.task_id)
  if (failure !== undefined) {
    state.failures.delete(task.task_id)
    entry.task = {
      ...task,
      status: 'failed',
      stage: null,
      error: { code: failure, message: KB_PACKAGE_MESSAGES[failure] ?? failure },
      finished_at: Date.now(),
    }
    releaseDataset(entry)
    return entry.task
  }

  const stages = entry.kind === 'export' ? KB_EXPORT_STAGES : KB_IMPORT_STAGES
  entry.step += 1
  const stage = stages[entry.step - 1]
  if (stage === undefined) {
    entry.task = {
      ...task,
      status: 'done',
      stage: null,
      done: task.total,
      progress: 1,
      message: 'Gotowe',
      finished_at: Date.now(),
      result: entry.result,
    }
    releaseDataset(entry)
  } else {
    const progress = Number((entry.step / (stages.length + 1)).toFixed(3))
    const done = Math.round(task.total * progress)
    entry.task = {
      ...task,
      status: 'running',
      stage,
      done,
      progress,
      message: `${KB_STAGE_LABELS[stage]} ${done}/${task.total}`,
    }
  }
  return entry.task
}

function createExportTask(preview: ExportPreview): MockTask {
  const taskId = nextId('task-')
  const createdAt = Date.now()
  const expiresAt = createdAt + KB_TTL_MS
  return {
    kind: 'export',
    step: 0,
    result: {
      download_url: `/api/wd/v1/exports/${taskId}/download?exp=${Math.floor(expiresAt / 1000)}&sig=${taskId}`,
      expires_at: expiresAt,
      size_bytes: preview.estimated_bytes_with_vectors,
      file_name: `${kbSlug(preview.name)}.wdkb.zip`,
    },
    task: {
      task_id: taskId,
      kind: 'export',
      dataset_id: preview.dataset_id,
      status: 'queued',
      stage: null,
      done: 0,
      total: preview.chunks,
      progress: 0,
      message: 'W kolejce',
      error: null,
      created_at: createdAt,
      finished_at: null,
      result: null,
    },
  }
}

function createImportTask(
  datasetImport: DatasetImport,
  name: string,
  reembedded: boolean,
  summary: ImportSummary,
): MockTask {
  const taskId = nextId('task-')
  const createdAt = Date.now()
  return {
    kind: 'import',
    step: 0,
    result: {
      dataset_id: nextId('dataset-'),
      dataset_name: name,
      documents: summary.documents,
      chunks: summary.chunks,
      reembedded,
    },
    task: {
      task_id: taskId,
      kind: 'import',
      dataset_id: datasetImport.import_id,
      status: 'queued',
      stage: null,
      done: 0,
      total: summary.chunks,
      progress: 0,
      message: 'W kolejce',
      error: null,
      created_at: createdAt,
      finished_at: null,
      result: null,
    },
  }
}

/**
 * Handlery tras 1–10 z K19 §3. Zadania tworzone przez `POST /export` i `POST /imports/{id}/start`
 * rozwijają się o krok przy każdym `GET /tasks/{id}` (do `done` włącznie) — pasek zadań (T4)
 * widzi postęp, a testy nie muszą czekać na zegarze.
 */
export function kbTransferHandlers(): HttpHandler[] {
  return [
    // 1. GET /datasets/{dataset_id}/export/preview
    http.get(apiUrl('/api/wd/v1/datasets/:datasetId/export/preview'), ({ params }) => {
      const lookup = lookupPreview(String(params.datasetId))
      return 'error' in lookup ? lookup.error : wdOk(lookup.preview)
    }),

    // 2. POST /datasets/{dataset_id}/export
    http.post(apiUrl('/api/wd/v1/datasets/:datasetId/export'), async ({ request, params }) => {
      const lookup = lookupPreview(String(params.datasetId))
      if ('error' in lookup) return lookup.error
      const preview = lookup.preview
      const body = await readJson(request)
      const includeVectors = body.include_vectors !== false
      const bytes = includeVectors ? preview.estimated_bytes_with_vectors : preview.estimated_bytes
      if (bytes > preview.max_bytes) {
        return wdError(413, 'package_too_large', `Paczka przekroczy limit ${preview.max_bytes} B.`)
      }
      const running = state.exportByDataset.get(preview.dataset_id)
      if (running !== undefined) {
        return wdError(409, 'export_in_progress', 'Eksport tej bazy wiedzy już trwa.', {
          task_id: running,
        })
      }
      const entry = createExportTask(preview)
      state.tasks.set(entry.task.task_id, entry)
      state.exportByDataset.set(preview.dataset_id, entry.task.task_id)
      return wdOk({ task_id: entry.task.task_id, status: 'queued' }, 202)
    }),

    // 3. GET /tasks/{task_id}
    http.get(apiUrl('/api/wd/v1/tasks/:taskId'), ({ params }) => {
      const entry = state.tasks.get(String(params.taskId))
      if (entry === undefined) return wdError(404, 'not_found', 'Nie znaleziono zadania.')
      return wdOk(advance(entry))
    }),

    // 4. POST /tasks/{task_id}/stop
    http.post(apiUrl('/api/wd/v1/tasks/:taskId/stop'), ({ params }) => {
      const entry = state.tasks.get(String(params.taskId))
      if (entry === undefined) return wdError(404, 'not_found', 'Nie znaleziono zadania.')
      const { task } = entry
      const finished =
        task.status === 'done' || task.status === 'failed' || task.status === 'cancelled'
      if (!finished) {
        entry.task = {
          ...task,
          status: 'cancelled',
          message: 'Zatrzymane',
          finished_at: Date.now(),
        }
        releaseDataset(entry)
      }
      return wdOk({ stopped: !finished })
    }),

    // 5. GET /exports/{task_id}/download — bez aktora, tylko podpis (K19 §3 trasa 5).
    http.get(apiUrl('/api/wd/v1/exports/:taskId/download'), ({ request, params }) => {
      const url = new URL(request.url)
      const entry = state.tasks.get(String(params.taskId))
      if (url.searchParams.get('sig') === null || entry === undefined) {
        return wdError(403, 'invalid_signature', 'Nieprawidłowy podpis linku pobrania.')
      }
      const exp = Number.parseInt(url.searchParams.get('exp') ?? '', 10)
      if (!Number.isFinite(exp) || exp * 1000 < Date.now()) {
        return wdError(410, 'export_expired', 'Link pobrania wygasł.')
      }
      const fileName = 'file_name' in entry.result ? entry.result.file_name : 'paczka.wdkb.zip'
      return HttpResponse.arrayBuffer(Uint8Array.from([0x50, 0x4b]).buffer, {
        status: 200,
        headers: {
          'Content-Type': 'application/zip',
          'Content-Disposition': `attachment; filename="${fileName}"`,
        },
      })
    }),

    // 6. POST /dataset-imports
    http.post(apiUrl('/api/wd/v1/dataset-imports'), async ({ request }) => {
      const body = await readJson(request)
      const fileName = typeof body.file_name === 'string' ? body.file_name : ''
      const sizeBytes = typeof body.size_bytes === 'number' ? body.size_bytes : 0
      if (
        fileName === '' ||
        fileName.length > 255 ||
        !Number.isInteger(sizeBytes) ||
        sizeBytes <= 0
      ) {
        return wdError(400, 'validation_failed', 'Nazwa pliku 1–255 znaków i rozmiar > 0 bajtów.')
      }
      if (sizeBytes > KB_MAX_BYTES) {
        return wdError(413, 'package_too_large', 'Paczka przekracza limit rozmiaru.')
      }
      const created: DatasetImport = {
        import_id: nextId('import-'),
        file_name: fileName,
        size_bytes: sizeBytes,
        received_bytes: 0,
        chunk_size: KB_CHUNK_SIZE,
        state: 'uploading',
        errors: [],
        summary: null,
        task_id: null,
        expires_at: Date.now() + KB_TTL_MS,
      }
      state.imports.set(created.import_id, created)
      return wdOk(created, 201)
    }),

    // 7. PUT /dataset-imports/{import_id}/content
    http.put(
      apiUrl('/api/wd/v1/dataset-imports/:importId/content'),
      async ({ request, params }) => {
        if (state.uploadFailures > 0) {
          state.uploadFailures -= 1
          return HttpResponse.error() // błąd sieci — wznawianie po stronie sesji wysyłki (T2)
        }
        const id = String(params.importId)
        const datasetImport = state.imports.get(id)
        if (datasetImport === undefined)
          return wdError(404, 'not_found', 'Nie znaleziono sesji importu.')
        const range = parseContentRange(request.headers.get('Content-Range'))
        if (range === null || range.total !== datasetImport.size_bytes) {
          return wdError(400, 'validation_failed', 'Nagłówek Content-Range niepoprawny.')
        }
        if (datasetImport.state !== 'uploading') {
          return wdError(409, 'import_not_ready', 'Sesja importu nie przyjmuje już porcji.', {
            state: datasetImport.state,
          })
        }
        if (range.start !== datasetImport.received_bytes) {
          return wdError(409, 'offset_mismatch', 'Porcja nie zgadza się z odebranymi bajtami.', {
            received_bytes: datasetImport.received_bytes,
          })
        }
        if (range.end - range.start + 1 > datasetImport.chunk_size) {
          return wdError(413, 'package_too_large', 'Porcja przekracza rozmiar chunk_size.')
        }
        const next: DatasetImport = {
          ...datasetImport,
          received_bytes: range.end + 1,
          expires_at: Date.now() + KB_TTL_MS,
        }
        if (next.received_bytes > next.size_bytes) {
          return wdError(400, 'validation_failed', 'Porcja wykracza poza rozmiar paczki.')
        }
        if (next.received_bytes === next.size_bytes) {
          // Walidacja paczki w tym samym żądaniu (K19 §3 trasa 7).
          if (Array.isArray(state.packageOutcome)) {
            next.state = 'invalid'
            next.errors = state.packageOutcome.map((error) => ({ ...error }))
          } else {
            next.state = 'ready'
            next.summary = cloneSummary(state.packageOutcome)
          }
        }
        state.imports.set(id, next)
        return wdOk(next)
      },
    ),

    // 8. GET /dataset-imports/{import_id}
    http.get(apiUrl('/api/wd/v1/dataset-imports/:importId'), ({ params }) => {
      const datasetImport = state.imports.get(String(params.importId))
      if (datasetImport === undefined) {
        return wdError(404, 'not_found', 'Nie znaleziono sesji importu.')
      }
      return wdOk(datasetImport)
    }),

    // 9. POST /dataset-imports/{import_id}/start
    http.post(apiUrl('/api/wd/v1/dataset-imports/:importId/start'), async ({ request, params }) => {
      const id = String(params.importId)
      const datasetImport = state.imports.get(id)
      if (datasetImport === undefined) {
        return wdError(404, 'not_found', 'Nie znaleziono sesji importu.')
      }
      const summary = datasetImport.summary
      if (datasetImport.state !== 'ready' || summary === null) {
        return wdError(409, 'import_not_ready', 'Sesja importu nie jest gotowa do startu.', {
          state: datasetImport.state,
        })
      }
      const body = await readJson(request)
      const name = typeof body.name === 'string' ? body.name.trim() : ''
      if (name === '' || name.length > 128) {
        return wdError(400, 'validation_failed', 'Nazwa 1–128 znaków.')
      }
      const requested = typeof body.embedding_model === 'string' ? body.embedding_model : null
      const model = requested ?? summary.target.default_model
      if (model === null) {
        return wdError(400, 'embedding_model_required', 'Wybierz model embeddingów.')
      }
      if (!summary.target.models.some((item) => item.name === model)) {
        return wdError(
          400,
          'embedding_model_unknown',
          'Wybrany model embeddingów jest niedostępny.',
        )
      }
      if (isTakenName(name)) {
        return wdError(409, 'name_conflict', 'Nazwa jest już zajęta.', {
          suggested_name: summary.suggested_name,
        })
      }
      const entry = createImportTask(
        datasetImport,
        name,
        model !== summary.embedding.model_name,
        summary,
      )
      state.tasks.set(entry.task.task_id, entry)
      state.takenNames.push(name)
      state.imports.set(id, {
        ...datasetImport,
        state: 'started',
        task_id: entry.task.task_id,
        expires_at: Date.now() + KB_TTL_MS,
      })
      return wdOk({ task_id: entry.task.task_id, status: 'queued' }, 202)
    }),

    // 10. DELETE /dataset-imports/{import_id}
    http.delete(apiUrl('/api/wd/v1/dataset-imports/:importId'), ({ params }) => {
      const id = String(params.importId)
      if (!state.imports.has(id)) return wdError(404, 'not_found', 'Nie znaleziono sesji importu.')
      state.imports.delete(id)
      return wdOk({ deleted: true })
    }),
  ]
}
