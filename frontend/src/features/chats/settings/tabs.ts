/**
 * Układ zakładek szuflady ustawień czatu: do której zakładki należy pole z błędem walidacji
 * i jak pokazać błąd zapisu (wydzielone z `ChatSettingsDrawer` przez limit rozmiaru pliku).
 */

import type { TFunction } from 'i18next'

import { ApiError } from '../../../api/envelope'
import { errorText } from '../../../lib/errorText'

export type TabValue = 'assistant' | 'prompt' | 'model'

export const TAB_VALUES: TabValue[] = ['assistant', 'prompt', 'model']

/**
 * Zakładka, na której leży pole — układ pól w zakładkach, nie reguły walidacji (te zostają
 * w `settings/schema.ts`). `prompt_config` jest rozdzielony: treść rozmowy na „Asystencie”,
 * ustawienia silnika na „Silniku promptu”.
 */
const TAB_OF_FIELD: Record<string, TabValue> = {
  name: 'assistant',
  description: 'assistant',
  dataset_ids: 'assistant',
  similarity_threshold: 'prompt',
  vector_similarity_weight: 'prompt',
  top_n: 'prompt',
  rerank_id: 'prompt',
  llm_id: 'model',
  llm_setting: 'model',
}

const PROMPT_TAB_PROMPT_FIELDS = new Set(['system', 'cross_languages', 'refine_multiturn'])

/** Zakładka pola wskazanego ścieżką błędu walidacji (pierwszy komunikat błędu). */
export function tabOfIssue(path: ReadonlyArray<PropertyKey>): TabValue {
  const [field = '', nested = ''] = path
  if (field === 'prompt_config') {
    return PROMPT_TAB_PROMPT_FIELDS.has(String(nested)) ? 'prompt' : 'assistant'
  }
  return TAB_OF_FIELD[String(field)] ?? 'assistant'
}

/**
 * Komunikat błędu zapisu (T3b): treść z `ApiError` tłumaczona wg INVENTORY (`errorText`),
 * a przy błędzie transportu — tekst z i18n. `null` = brak błędu.
 */
export function mutationError(error: unknown, fallback: string, t: TFunction): string | null {
  if (error === null || error === undefined) return null
  if (error instanceof ApiError && error.message !== '') return errorText(error, t)
  return fallback
}
