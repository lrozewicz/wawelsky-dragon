// Odpowiednik `IngestionLog` z backend/openapi.json (GET …/ingestions) — pola czytane przez
// zakładkę Logi (08 §7.4); `operation_status` to kod `run` 0–5 jako napis (kontrakt §Fakty API).
export type FixtureIngestionLog = {
  id: string
  kb_id: string
  document_id: string
  document_name: string
  document_type: string
  task_type: string
  process_begin_at: string
  process_duration: number
  operation_status: string
  progress: number
  progress_msg: string
  create_time: number
}

export function fixtureIngestionLog(
  overrides: Partial<FixtureIngestionLog> = {},
): FixtureIngestionLog {
  return {
    id: 'log-1',
    kb_id: 'ds-1',
    document_id: 'doc-1',
    document_name: 'umowa.pdf',
    document_type: 'pdf',
    task_type: 'file',
    process_begin_at: '2025-01-01 00:05:00',
    process_duration: 12.5,
    operation_status: '3',
    progress: 1,
    progress_msg: 'Done',
    create_time: 1735689600000,
    ...overrides,
  }
}

// Odpowiednik `IngestionSummary` z backend/openapi.json (GET …/ingestions/summary) — liczby
// dokumentów i ich stany `run` dla kart statystyk zakładki Logi.
export type FixtureIngestionSummary = {
  doc_num: number
  chunk_num: number
  token_num: number
  status: {
    cancel_count: number
    done_count: number
    fail_count: number
    running_count: number
    unstart_count: number
  }
}

export function fixtureIngestionSummary(
  overrides: Partial<FixtureIngestionSummary> = {},
): FixtureIngestionSummary {
  return {
    doc_num: 3,
    chunk_num: 12,
    token_num: 2500,
    status: { cancel_count: 0, done_count: 1, fail_count: 1, running_count: 0, unstart_count: 1 },
    ...overrides,
  }
}
