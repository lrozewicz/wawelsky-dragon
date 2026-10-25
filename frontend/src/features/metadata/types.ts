/**
 * Typy modułu metadanych (kontrakt WP E6-1b §2): operatory warunków, filtry metodą
 * `meta_data_filter` (czat/Search/retrieval) i pola konfiguracji datasetu. Same typy i stałe —
 * bez Reacta i sieci; konwersje siedzą w `convert.ts`, zapytania w `queries.ts`.
 */

/** Czternaście operatorów warunków — wspólne dla UI i `meta_data_filter` (kontrakt §1/§2). */
export const META_OPS = [
  '=',
  '≠',
  '>',
  '<',
  '≥',
  '≤',
  'contains',
  'not contains',
  'start with',
  'end with',
  'in',
  'not in',
  'empty',
  'not empty',
] as const

export type MetaOp = (typeof META_OPS)[number]

/** Operatory bez pola wartości — `value` jest wtedy `''` (kontrakt §1: `empty` wymaga klucza `value`). */
export const NO_VALUE_OPS: readonly MetaOp[] = ['empty', 'not empty']

/** Operatory przyjmujące listę wartości (`string[]`). */
export const LIST_VALUE_OPS: readonly MetaOp[] = ['in', 'not in']

/** Pole formularza konfiguracji datasetu (`metadata/config`); UI zawsze wysyła `type: 'string'`. */
export type MetaFieldDef = { key: string; description: string; enum: string[] }

/** Pojedynczy warunek kreatora: `''` dla `NO_VALUE_OPS`, `string[]` dla `LIST_VALUE_OPS`. */
export type MetaCondition = { key: string; op: MetaOp; value: string | string[] }

/** Tryb filtra: wyłączony / ręczny / automatyczny / półautomatyczny (kontrakt §1). */
export type MetaFilterMethod = 'off' | 'manual' | 'auto' | 'semi_auto'

/** Stan kreatora warunków; `{}` po stronie drutu odpowiada temu obiektowi. */
export type MetaFilter = {
  method: MetaFilterMethod
  logic: 'and' | 'or'
  manual: MetaCondition[]
  semi_auto: string[]
}

/** Filtr wyłączony — wartość startowa kreatora i wynik „pustego” drutu. */
export const EMPTY_META_FILTER: MetaFilter = {
  method: 'off',
  logic: 'and',
  manual: [],
  semi_auto: [],
}
