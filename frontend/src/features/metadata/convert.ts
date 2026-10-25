/**
 * Konwersje między kształtem drutu a modelem UI (kontrakt WP E6-1b §2). Czyste funkcje —
 * bez Reacta i sieci — pokryte w 100% gałęzi w `convert.test.ts`. Tolerancja wobec danych
 * z backendu (kontrakt §1): nieznany kształt degraduje się do pustego filtra, a nie rzuca.
 */

import { META_OPS } from './types'
import type { MetaCondition, MetaFieldDef, MetaFilter, MetaOp } from './types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

const META_OPS_SET: ReadonlySet<string> = new Set(META_OPS)

function isMetaOp(value: unknown): value is MetaOp {
  return typeof value === 'string' && META_OPS_SET.has(value)
}

/** Świeży obiekt pustego filtra — `EMPTY_META_FILTER` jest współdzieloną stałą (bez mutacji). */
function emptyFilter(): MetaFilter {
  return { method: 'off', logic: 'and', manual: [], semi_auto: [] }
}

/** Warunek z drutu; `null`, gdy brak klucza, nieznany operator albo wartość innego typu. */
function conditionFromWire(raw: unknown): MetaCondition | null {
  if (!isRecord(raw)) return null
  const { key, op, value } = raw
  if (typeof key !== 'string' || key.trim() === '' || !isMetaOp(op)) return null
  if (typeof value === 'string') return { key, op, value }
  if (Array.isArray(value)) return { key, op, value: value.map((item) => String(item)) }
  return null
}

/** `meta_data_filter` z drutu: `{}` / `null` / nieznany `method` → pusty filtr (kontrakt §2). */
export function filterFromWire(raw: Record<string, unknown> | null | undefined): MetaFilter {
  if (!isRecord(raw)) return emptyFilter()
  const method = raw.method
  if (method !== 'manual' && method !== 'auto' && method !== 'semi_auto') return emptyFilter()
  const logic: 'and' | 'or' = raw.logic === 'or' ? 'or' : 'and'
  if (method === 'manual') {
    const manual = Array.isArray(raw.manual)
      ? raw.manual.map(conditionFromWire).filter((c): c is MetaCondition => c !== null)
      : []
    return { method, logic, manual, semi_auto: [] }
  }
  if (method === 'semi_auto') {
    const semi_auto = Array.isArray(raw.semi_auto)
      ? raw.semi_auto.filter((key): key is string => typeof key === 'string')
      : []
    return { method, logic, manual: [], semi_auto }
  }
  return { method, logic, manual: [], semi_auto: [] }
}

/** Filtr do ciała żądania: `off` → `{}`, reszta metod wg kontraktu §2. */
export function filterToWire(f: MetaFilter): Record<string, unknown> {
  if (f.method === 'off') return {}
  if (f.method === 'manual') return { method: 'manual', logic: f.logic, manual: f.manual }
  if (f.method === 'semi_auto') return { method: 'semi_auto', semi_auto: f.semi_auto }
  return { method: 'auto' }
}

/** `?metadata_condition=<JSON>` listy dokumentów; `[]` (albo same warunki bez klucza) → `undefined`. */
export function conditionsToDocumentsParam(
  logic: 'and' | 'or',
  conds: MetaCondition[],
): string | undefined {
  const conditions = conds
    .filter((c) => c.key.trim() !== '')
    .map((c) => ({ name: c.key, comparison_operator: c.op, value: c.value }))
  if (conditions.length === 0) return undefined
  return JSON.stringify({ logic, conditions })
}

/** Walidacja wierszy formularza pola (po indeksie): pusty klucz → `required`, powtórzony → `duplicate`. */
export function validateFieldDefs(fields: MetaFieldDef[]): Array<'ok' | 'required' | 'duplicate'> {
  const seen = new Set<string>()
  return fields.map((field) => {
    const key = field.key.trim()
    if (key === '') return 'required'
    if (seen.has(key)) return 'duplicate'
    seen.add(key)
    return 'ok'
  })
}

type WireField = { key: string; description: string | null; enum: string[] | null }

/** Pola z drutu (`description`/`enum` mogą być `null`) → formularz (`''`/`[]`). */
export function fieldsFromWire(list: WireField[]): MetaFieldDef[] {
  return list.map((field) => ({
    key: field.key,
    description: field.description ?? '',
    enum: field.enum ?? [],
  }))
}

/** Formularz → ciało PUT: `trim` klucza, stały `type: 'string'`, puste `description`/`enum` → `null`. */
export function fieldsToWire(
  fields: MetaFieldDef[],
): Array<{ key: string; type: 'string'; description: string | null; enum: string[] | null }> {
  return fields.map((field) => ({
    key: field.key.trim(),
    type: 'string',
    description: field.description === '' ? null : field.description,
    enum: field.enum.length === 0 ? null : field.enum,
  }))
}

/** Wartość metadanej jako tekst: lista → elementy po `', '`, `null`/`undefined` → `''`. */
function formatMetaValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(', ')
  if (value === null || value === undefined) return ''
  return String(value)
}

/**
 * Chipy kolumny „Metadane” (kontrakt §2): `klucz: wartość`, kolejność kluczy jak w obiekcie.
 * `text` i `full` niosą dziś ten sam napis — obcięcie wizualne robi CSS (wielokropek), a `full`
 * trafia na atrybut `title` chipu.
 */
export function summarizeMeta(
  meta: Record<string, unknown> | null | undefined,
): Array<{ key: string; text: string; full: string }> {
  if (!isRecord(meta)) return []
  return Object.entries(meta).map(([key, value]) => {
    const text = `${key}: ${formatMetaValue(value)}`
    return { key, text, full: text }
  })
}

/** Wiersz szuflady: `untouched` trzyma oryginalną wartość, by nie zgubić typu liczby/bool. */
export type MetaRow = { key: string; value: string | string[]; untouched: unknown }

/** `meta_fields` dokumentu → wiersze szuflady (lista → `string[]`, reszta → `string`). */
export function metaToRows(meta: Record<string, unknown> | null | undefined): MetaRow[] {
  if (!isRecord(meta)) return []
  return Object.entries(meta).map(([key, raw]) => ({
    key,
    value: Array.isArray(raw) ? raw.map((item) => String(item)) : formatMetaValue(raw),
    untouched: raw,
  }))
}

/**
 * Wiersze szuflady → `meta_fields`: puste klucze pomijane; wartość nietknięta zachowuje
 * oryginalny typ (liczba/bool), edytowana idzie jako tekst (kontrakt §2).
 */
export function rowsToMeta(rows: MetaRow[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const row of rows) {
    const key = row.key.trim()
    if (key === '') continue
    if (Array.isArray(row.value)) out[key] = row.value
    else if (typeof row.untouched !== 'string' && String(row.untouched) === row.value) {
      out[key] = row.untouched
    } else {
      out[key] = row.value
    }
  }
  return out
}
