/**
 * Pola formularza konfiguracji datasetu (08 §8.1, kontrakt WP E3-3a §T4): schemat zod,
 * mapowanie datasetu na wartości formularza i `buildConfigPatch`.
 *
 * Formularz trzyma obok pól top-level (`name`, `description`, `language`, `permission`,
 * `embedding_model`, `chunk_method`) także pola `parser_config`. Backend przy PUT może
 * zastąpić obiekt `parser_config` w całości, więc wysyłamy scaloną całość — łącznie z kluczami,
 * których formularz nie zna (np. `raptor`, `parent_child`) — dopiero gdy któreś pole się zmieniło.
 * `embedding_model` trzyma NAZWĘ modelu (taką, jak w `Dataset.embedding_model`), a nie `model_id`.
 *
 * DROP-pola z §8.1 (`avatar`, `pagerank`, `tag_kb_ids`, `topn_tags`, `parse_type`,
 * `pipeline_id`) i pola bez wsparcia w M5 (`enable_children`, `table_column_*`) nie mają
 * odpowiedników w `ConfigValues` — formularz ich nie renderuje.
 */

import { z } from 'zod'

import type { Model } from '../../chats/modelsQuery'
import { fieldsToWire } from '../../metadata/convert'
import type { MetaFieldDef } from '../../metadata/types'
import { CHUNK_METHODS } from '../queries'
import type { ChunkMethod, Dataset } from '../queries'

/**
 * Zakresy stron `parser_config.pages` (§T4): liczby całkowite ≥ 1, `od ≤ do`, bez nakładania.
 * `null` to puste pole „Od”/„Do” (SC-E5-H9-05): wiersz całkiem pusty jest przy zapisie
 * pomijany, a półpełny dostaje `errorIncomplete`. Wszystkie komunikaty lądują na ścieżce
 * `pages` (błąd pokazywany raz pod edytorem), dlatego reguły liczbowe są w `superRefine`,
 * a nie w schemacie pojedynczego elementu.
 */
const pagesSchema = z
  .array(z.tuple([z.number().nullable(), z.number().nullable()]))
  .superRefine((pages, ctx) => {
    for (const [from, to] of pages) {
      if (from === null && to === null) continue
      if (from === null || to === null) {
        ctx.addIssue('datasets.config.pages.errorIncomplete')
        continue
      }
      if (!Number.isInteger(from) || !Number.isInteger(to) || from < 1 || to < 1) {
        ctx.addIssue('datasets.config.pages.errorMin')
      }
      if (from > to) ctx.addIssue('datasets.config.pages.errorOrder')
    }
    // Po sortowaniu po `from` bieżący zakres nachodzi na poprzednie, gdy zaczyna się nie później
    // niż maksymalny dotychczasowy koniec (obejmuje też zagnieżdżenia).
    const sorted = [...pages].filter(isCompleteRange).sort((left, right) => left[0] - right[0])
    let maxEnd = 0
    for (const [from, to] of sorted) {
      // Zakresy z `from < 1` są już błędne (`errorMin`) — pomijamy je w wykrywaniu nakładania.
      if (from >= 1 && from <= maxEnd) ctx.addIssue('datasets.config.pages.errorOverlap')
      maxEnd = Math.max(maxEnd, to)
    }
  })

/** Zakres stron w formularzu: `null` = niewypełnione pole „Od”/„Do”. */
export type PageRange = [number | null, number | null]

/** Wiersz z oboma polami wypełnionymi — tylko takie trafiają do `parser_config`. */
export function isCompleteRange(range: PageRange): range is [number, number] {
  return range[0] !== null && range[1] !== null
}

export type ConfigValues = {
  name: string
  description: string
  language: string
  permission: 'me' | 'team'
  /** NAZWA modelu embeddingu (jak w `Dataset.embedding_model`), nie `model_id`. */
  embedding_model: string
  chunk_method: ChunkMethod
  /**
   * 'DeepDOC' | 'Plain Text' | NAZWA modelu image2text (§T4). Wartość spoza tego zbioru
   * (np. stare `VLM`) jest błędem walidacji widocznym w selekcie (kontrakt E5-H3 §#9).
   */
  layout_recognize: string
  chunk_token_num: number
  delimiter: string
  overlapped_percent: number
  html4excel: boolean
  auto_keywords: number
  auto_questions: number
  llm_id: string
  /** Zakresy stron `parser_config.pages` (`[od, do]`, 1-based, włącznie); `[]` = wszystkie. */
  pages: PageRange[]
  /** Auto-metadane `parser_config.enable_metadata` (kontrakt WP E6-1b §1). */
  enable_metadata: boolean
}

/** Pola `ConfigValues` przenoszone do `parser_config` (reszta idzie top-level). */
const PARSER_FIELDS = [
  'layout_recognize',
  'chunk_token_num',
  'delimiter',
  'overlapped_percent',
  'html4excel',
  'auto_keywords',
  'auto_questions',
  'llm_id',
  'pages',
  'enable_metadata',
] as const

/**
 * Stałe opcje parsera PDF (`parser_config.layout_recognize`) — literały backendu i klucze etykiet
 * (§T4). Trzymane razem z modelem wizji, bo select łączy je z nazwami modeli image2text.
 */
export const LAYOUT_OPTIONS = [
  { value: 'DeepDOC', labelKey: 'datasets.config.layout.auto' },
  { value: 'Plain Text', labelKey: 'datasets.config.layout.plain' },
] as const

/** Wartości parsera spoza modeli wizji (stałe; nazwy modeli image2text dokładane dynamicznie). */
export const LAYOUT_VALUES: readonly string[] = LAYOUT_OPTIONS.map((option) => option.value)

/**
 * Typ modelu wizji w `GET /api/v1/models`: backend trzyma `image2text`, ale mapuje go na `vision`
 * (`backend/app/api/ragflow/routes/models.py:35`), a UI akceptuje oba oznaczenia (jak
 * `DefaultModelsCard`). Filtr po `vision` jest konieczny, by e2e z prawdziwym API widział modele.
 */
const VISION_MODEL_TYPES: readonly string[] = ['image2text', 'vision']

/** Podzbiór `Model` potrzebny do wyliczenia nazw opcji selecta (bez zależności od warstwy czatu). */
type ModelLike = { name: string; model_type: string[] }

/**
 * Nazwy modeli wizji (§T4) — BEZ wstrzykiwania bieżącej wartości: wartość spoza listy ma zostać
 * nierozpoznana, żeby select pokazał „nieznany model" i zablokował zapis.
 */
export function visionModelNames(models: readonly ModelLike[]): string[] {
  const names = models
    .filter((model) => model.model_type.some((type) => VISION_MODEL_TYPES.includes(type)))
    .map((model) => model.name)
  return [...new Set(names)]
}

export const configSchema: z.ZodType<ConfigValues> = z.object({
  name: z.string().trim().min(1, 'common.required'),
  description: z.string().max(512, 'datasets.config.descriptionMax'),
  language: z.string(),
  permission: z.enum(['me', 'team']),
  embedding_model: z.string(),
  chunk_method: z.enum(CHUNK_METHODS),
  layout_recognize: z.string(),
  chunk_token_num: z.number().int().min(64).max(2048),
  delimiter: z.string(),
  overlapped_percent: z.number().min(0).max(30),
  html4excel: z.boolean(),
  auto_keywords: z.number().int().min(0).max(30),
  auto_questions: z.number().int().min(0).max(10),
  llm_id: z.string(),
  pages: pagesSchema,
  enable_metadata: z.boolean(),
})

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function text(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

function flag(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function chunkMethodOf(value: string): ChunkMethod {
  return CHUNK_METHODS.find((method) => method === value) ?? 'naive'
}

/** `parser_config.pages` → zakresy formularza; wpisy niepoprawne kształtem pomijamy (domyślnie `[]`). */
function pagesOf(value: unknown): [number, number][] {
  if (!Array.isArray(value)) return []
  const pages: [number, number][] = []
  for (const entry of value) {
    if (!Array.isArray(entry)) continue
    const [from, to] = entry
    if (typeof from === 'number' && typeof to === 'number') pages.push([from, to])
  }
  return pages
}

/** Porównanie zawartości zakresów — tablice z `datasetToValues` są zawsze świeże (referencja ≠). */
function samePages(left: PageRange[], right: PageRange[]): boolean {
  return (
    left.length === right.length &&
    left.every((page, index) => page[0] === right[index]![0] && page[1] === right[index]![1])
  )
}

/** Wartości początkowe formularza z pobranego datasetu; brakujące klucze dostają domyślne backendu. */
export function datasetToValues(dataset: Dataset): ConfigValues {
  const raw = isRecord(dataset.parser_config) ? dataset.parser_config : {}

  return {
    name: dataset.name,
    description: dataset.description ?? '',
    language: dataset.language,
    permission: dataset.permission,
    embedding_model: dataset.embedding_model,
    chunk_method: chunkMethodOf(dataset.chunk_method),
    layout_recognize: text(raw.layout_recognize, 'DeepDOC'),
    chunk_token_num: numberOr(raw.chunk_token_num, 512),
    delimiter: text(raw.delimiter, '\n'),
    overlapped_percent: numberOr(raw.overlapped_percent, 0),
    html4excel: flag(raw.html4excel, false),
    auto_keywords: numberOr(raw.auto_keywords, 0),
    auto_questions: numberOr(raw.auto_questions, 0),
    llm_id: text(raw.llm_id, ''),
    pages: pagesOf(raw.pages),
    enable_metadata: flag(raw.enable_metadata, false),
  }
}

/**
 * Łatka PUT z WYŁĄCZNIE zmienionych pól (08 §8.1); brak zmian → `{}`. `parser_config` wysyłamy
 * jako pełny, scalony obiekt (z kluczami nieobsługiwanymi przez UI), bo backend może zastąpić go
 * w całości. `embedding_model` pomijamy przy istniejących chunkach — backend odrzuca taką zmianę,
 * a pole jest wtedy zablokowane w formularzu.
 *
 * `metadata` to pola auto-metadanych z osobnego zapytania `metadata/config` (kontrakt WP E6-1b
 * §1): gdy ich lista różni się od zapisanej w `parser_config.metadata`, PUT datasetu niesie
 * NOWĄ listę — inaczej nadpisałby zapis `PUT …/metadata/config`, który w „Zapisz” idzie pierwszy.
 */
export function buildConfigPatch(
  dataset: Dataset,
  values: ConfigValues,
  metadata?: MetaFieldDef[],
  models: readonly Model[] = [],
): Record<string, unknown> {
  const initial = datasetToValues(dataset)
  const patch: Record<string, unknown> = {}
  const name = values.name.trim()

  if (name !== initial.name) patch.name = name
  if (values.description !== initial.description) patch.description = values.description
  if (values.language !== initial.language) patch.language = values.language
  if (values.permission !== initial.permission) patch.permission = values.permission
  if (dataset.chunk_count <= 0 && values.embedding_model !== initial.embedding_model) {
    // Backend chce `<nazwa>@<dostawca>` albo id modelu, nie samą nazwę.
    const model = models.find(
      (m) => m.model_type.includes('embedding') && m.name === values.embedding_model,
    )
    patch.embedding_model = model?.model_id ?? values.embedding_model
  }
  if (values.chunk_method !== initial.chunk_method) patch.chunk_method = values.chunk_method

  const parser: Record<string, unknown> = {}
  // Niewypełnione wiersze zakresu pomijamy (SC-E5-H9-05) — pusty wiersz nie zmienia `pages`.
  const completePages = values.pages.filter(isCompleteRange)
  for (const field of PARSER_FIELDS) {
    // `pages` to tablica — porównujemy zawartość; pozostałe pola przez wartość/`!==`.
    const changed =
      field === 'pages'
        ? !samePages(completePages, initial.pages)
        : values[field] !== initial[field]
    if (changed) parser[field] = field === 'pages' ? completePages : values[field]
  }
  if (metadata !== undefined) {
    // Porównanie kształtu drutu (trim klucza, `null` dla pustych) — dokładnie to, co trzyma
    // `parser_config.metadata` backendu, więc różnica jest jednoznaczna ze zmianą.
    const wire = fieldsToWire(metadata)
    const raw = isRecord(dataset.parser_config) ? dataset.parser_config : {}
    const base = Array.isArray(raw.metadata) ? raw.metadata : []
    if (JSON.stringify(wire) !== JSON.stringify(base)) {
      parser.metadata = wire
    }
  }
  if (Object.keys(parser).length > 0) {
    patch.parser_config = { ...dataset.parser_config, ...parser }
  }

  return patch
}
