/**
 * Typy eksportu/importu bazy wiedzy (kontrakt WP E7-2 §2, źródło: K19 §3).
 * Pisane ręcznie — trasy K19 nie są jeszcze w `backend/openapi.json`, więc nie ma ich
 * w `src/api/schema.gen.ts` (dopisze je E7-1).
 */

/** Status zadania kolejki widziany przez UI (K19 §3: wewnętrzne `dead` → `failed`). */
export type WdTaskStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

/** Etap zadania — eksport: files→chunks→vectors→finalize; import: files→…→finalize. */
export type WdTaskStage = 'files' | 'documents' | 'chunks' | 'vectors' | 'embedding' | 'finalize'

export interface ExportPreview {
  dataset_id: string
  name: string
  documents: number
  chunks: number
  estimated_bytes: number
  estimated_bytes_with_vectors: number
  embedding: { model_name: string; dimension: number }
  max_bytes: number
}

export interface TaskRef {
  task_id: string
  status: 'queued'
}

export interface ExportResult {
  download_url: string
  expires_at: number
  size_bytes: number
  file_name: string
}

export interface ImportResult {
  dataset_id: string
  dataset_name: string
  documents: number
  chunks: number
  reembedded: boolean
}

export interface WdTask {
  task_id: string
  kind: 'export' | 'import'
  dataset_id: string | null
  status: WdTaskStatus
  stage: WdTaskStage | null
  done: number
  total: number
  progress: number
  message: string
  error: { code: string; message: string } | null
  created_at: number
  finished_at: number | null
  result: ExportResult | ImportResult | null
}

export type ImportState = 'uploading' | 'ready' | 'invalid' | 'started' | 'expired'

export interface ImportSummary {
  name: string
  description: string | null
  documents: number
  chunks: number
  schema_version: number
  wd_version: string
  created_at: string
  embedding: { model_name: string; dimension: number; included: boolean }
  target: {
    compatible: boolean
    default_model: string | null
    models: { name: string; dimension: number }[]
  }
  suggested_name: string
  name_taken: boolean
  estimated_reembed_tokens: number
}

export interface DatasetImport {
  import_id: string
  file_name: string
  size_bytes: number
  received_bytes: number
  chunk_size: number
  state: ImportState
  errors: { code: string; message: string }[]
  summary: ImportSummary | null
  task_id: string | null
  expires_at: number
}

/** Wiersz paska zadań pamiętany w localStorage (klucz `wd.kbTasks.v1:<userId>`). */
export interface StoredKbTask {
  task_id: string
  kind: 'export' | 'import'
  label: string // label = nazwa bazy do wyświetlenia
  dataset_id: string | null
  added_at: number // ms; wpis usuwany po added_at + 24 h
  finished_at?: number // ms; pierwsze odpytanie ze statusem końcowym — od niego liczy się 24 h zakończonego wiersza
  last: WdTask | null // ostatni znany stan (do pokazania przed pierwszym odpytaniem po F5)
}
