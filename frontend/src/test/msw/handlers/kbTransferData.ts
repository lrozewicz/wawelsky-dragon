/**
 * Ziarna i drobne pomocniki handlerów MSW eksportu/importu (kontrakt WP E7-2 §1; wzór:
 * `adminData.ts`, `settingsData.ts`). Wartości zgodne z K19 §3 — liczby jak w makiecie 08 §7.15.
 */

import type { ExportPreview, ImportSummary, WdTaskStage } from '../../../features/kb-transfer/types'

/** Identyfikator datasetu z ziarna domyślnego (kontrakt §3: `previewExport('d1')`). */
export const KB_DATASET_ID = 'd1'

/** `chunk_size` sesji importu (K19 §3 trasa 6). */
export const KB_CHUNK_SIZE = 8 * 1024 * 1024

/** `WD_EXPORT_MAX_BYTES` (K19 §5, domyślnie 2 GiB). */
export const KB_MAX_BYTES = 2 * 1024 * 1024 * 1024

/** Ważność sesji importu i linku pobrania: 24 h (K19 §4, §3 trasa 5). */
export const KB_TTL_MS = 24 * 60 * 60 * 1000

/** Etapy zadań widoczne w pasku (K19 §3: eksport files→…→finalize, import z `embedding`). */
export const KB_EXPORT_STAGES: readonly WdTaskStage[] = ['files', 'chunks', 'vectors', 'finalize']
export const KB_IMPORT_STAGES: readonly WdTaskStage[] = [
  'files',
  'documents',
  'chunks',
  'vectors',
  'embedding',
  'finalize',
]

/** Nazwa etapu w komunikacie zadania (`message` po polsku, np. „Chunki 3 000/7 251”). */
export const KB_STAGE_LABELS: Record<WdTaskStage, string> = {
  files: 'Pliki',
  documents: 'Dokumenty',
  chunks: 'Chunki',
  vectors: 'Wektory',
  embedding: 'Embeddingi',
  finalize: 'Finalizacja',
}

/** Komunikaty błędów walidacji paczki po polsku (K19 §3, `not_a_package` z K20 §2). */
export const KB_PACKAGE_MESSAGES: Record<string, string> = {
  not_a_package: 'To nie jest paczka bazy wiedzy Wawelsky Dragon (brak pliku manifest.json).',
  invalid_archive: 'Plik nie jest paczką Wawelsky Dragon (uszkodzone archiwum).',
  manifest_invalid: 'Paczka ma niepoprawny manifest.',
  schema_too_new: 'Paczka z nowszej wersji Wawelsky Dragon (schemat 2) — zaktualizuj instalację.',
  unsafe_path: 'Paczka zawiera niebezpieczną ścieżkę wpisu.',
  archive_too_large: 'Rozpakowana paczka przekracza limit rozmiaru.',
  checksum_mismatch: 'Paczka uszkodzona (suma kontrolna).',
  missing_entry: 'W paczce brakuje pliku wymienionego w manifeście.',
  unexpected_entry: 'Paczka zawiera plik spoza manifestu.',
  dimension_mismatch: 'Wektory w paczce mają inny wymiar niż deklarowany.',
}

/** Domyślny podgląd eksportu (K19 §3 trasa 1). */
export function kbDefaultPreview(): ExportPreview {
  return {
    dataset_id: KB_DATASET_ID,
    name: 'Rocznik GUS 2024',
    documents: 3,
    chunks: 7251,
    estimated_bytes: 31_457_280,
    estimated_bytes_with_vectors: 77_594_624,
    embedding: { model_name: 'text-embedding-3-small', dimension: 1536 },
    max_bytes: KB_MAX_BYTES,
  }
}

/** Domyślne podsumowanie paczki po walidacji (K19 §3 `ImportSummary`). */
export function kbDefaultSummary(): ImportSummary {
  return {
    name: 'Rocznik GUS 2024',
    description: 'Wybrane tablice GUS',
    documents: 3,
    chunks: 7251,
    schema_version: 1,
    wd_version: '1.3.0',
    created_at: '2026-10-12T21:00:00Z',
    embedding: { model_name: 'text-embedding-3-small', dimension: 1536, included: true },
    target: {
      compatible: true,
      default_model: 'text-embedding-3-small',
      models: [
        { name: 'text-embedding-3-small', dimension: 1536 },
        { name: 'bge-m3', dimension: 1024 },
      ],
    },
    suggested_name: 'Rocznik GUS 2024 (import 2026-10-13)',
    name_taken: true,
    estimated_reembed_tokens: 1_900_000,
  }
}

/**
 * Slug nazwy datasetu do nazwy pliku paczki (`<slug>.wdkb.zip`, K19 §2). Diakrytyki PL
 * transliterujemy (ż→z, ó→o, ł→l), zamiast wycinać nie-ASCII do pustego slugu; gdy z nazwy
 * nie zostaje żaden znak — awaryjnie „paczka”.
 */
export function kbSlug(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/ł/g, 'l')
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
  return slug === '' ? 'paczka' : slug
}
