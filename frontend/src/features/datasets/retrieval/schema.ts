/**
 * Ustawienia i pomocnicze funkcje testu retrievalu (kontrakt WP E3-4b §R/schema.ts):
 * typ ustawień, domyślne wartości, walidacja zod, formatowanie procentów i dzielenie
 * wyróżnień `<em>…</em>` na części bez HTML (bez `dangerouslySetInnerHTML`).
 */

import { z } from 'zod'

import { EMPTY_META_FILTER } from '../../metadata/types'
import type { MetaFilter } from '../../metadata/types'

export type RetrievalSettings = {
  /** Próg podobieństwa 0–1. */
  similarityThreshold: number
  /** Waga podobieństwa wektorowego 0–1. */
  vectorWeight: number
  /** Liczba wyników, całkowita 1–100. */
  topN: number
  /** Nazwa modelu rerank; `''` = brak. */
  rerankId: string
  /** Języki docelowe przepisania pytania; `[]` = bez przepisywania (K4 E3-H2a, zastępuje DEC-143 p. 1). */
  crossLanguages: string[]
  /** Filtr metadanych (E6-1b, tryby off/manual); drut w `buildRetrievalBody` przez `filterToWire`. */
  metaDataFilter: MetaFilter
}

/**
 * Języki wyszukiwania międzyjęzykowego — wartości wysyłane w `cross_languages`
 * (upstream ragflow `web/src/components/cross-language-form-field.tsx`).
 */
export const RETRIEVAL_LANGUAGES = [
  'English',
  'Chinese',
  'Spanish',
  'French',
  'German',
  'Japanese',
  'Korean',
  'Vietnamese',
  'Arabic',
  'Turkish',
  'Dutch',
] as const

export const DEFAULT_SETTINGS: RetrievalSettings = {
  similarityThreshold: 0.2,
  vectorWeight: 0.3,
  topN: 10,
  rerankId: '',
  crossLanguages: [],
  metaDataFilter: EMPTY_META_FILTER,
}

export const settingsSchema: z.ZodType<RetrievalSettings> = z.object({
  similarityThreshold: z.number().min(0).max(1),
  vectorWeight: z.number().min(0).max(1),
  topN: z.number().int().min(1).max(100),
  rerankId: z.string(),
  crossLanguages: z.array(z.string()),
  // Filtr buduje `MetadataConditionBuilder` — zawsze poprawny `MetaFilter` (kontrakt WP E6-1b §2).
  metaDataFilter: z.custom<MetaFilter>(),
})

/**
 * Czy filtr realnie zawęża wyniki (kontrakt §1: wyłączony = `{}`, a ręczny bez warunków niczego
 * nie odfiltrowuje). Decyduje o wysłaniu `meta_data_filter` w `/retrieval` i o komunikacie
 * pustego stanu „wykluczył wszystkie dokumenty”.
 */
export function isMetaFilterActive(filter: MetaFilter): boolean {
  if (filter.method === 'manual') return filter.manual.length > 0
  return filter.method !== 'off'
}

/** Pytanie testu: po przycięciu białych znaków musi mieć co najmniej jeden znak. */
export const questionSchema: z.ZodString = z.string().trim().min(1)

/** Procent z jednym miejscem po przecinku: `0.85` → `"85.0"`. */
export function formatPercent(value: number): string {
  return (value * 100).toFixed(1)
}

export type HighlightPart = { text: string; match: boolean }

/** Znacznik inny niż `<em>`/`</em>` (z atrybutami) — do usunięcia z tekstu. */
const OTHER_TAG = /<(?!\/?em\b)[^>]*>/gi
/** Wyróżniony fragment wyniku. */
const EM_SPAN = /<em>([\s\S]*?)<\/em>/g

/**
 * Dzieli `<em>…</em>` na części bez HTML: `'a <em>b</em> c'` → `[{a ,false},{b,true},{ c,false}]`;
 * pusty/undefined → `[]`. Inne tagi usuwa (tekst zostaje), pustych części nie zwraca.
 */
export function parseHighlight(html: string | null | undefined): HighlightPart[] {
  if (html === null || html === undefined || html === '') return []

  const cleaned = html.replace(OTHER_TAG, '')
  const parts: HighlightPart[] = []
  let cursor = 0

  for (const match of cleaned.matchAll(EM_SPAN)) {
    if (match.index > cursor) {
      parts.push({ text: cleaned.slice(cursor, match.index), match: false })
    }
    const inner = match[1] ?? ''
    if (inner !== '') parts.push({ text: inner, match: true })
    cursor = match.index + match[0].length
  }

  if (cursor < cleaned.length) parts.push({ text: cleaned.slice(cursor), match: false })

  return parts
}
