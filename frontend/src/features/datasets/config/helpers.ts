/**
 * Pomocniki zakładki „Konfiguracja” datasetu, wydzielone z `ConfigurationTab.tsx` przez limit
 * rozmiaru pliku (DEC-098): nazwy modeli dla selektów, komunikat błędu mutacji, podgląd
 * separatora i powód nieaktywnego „Zapisz”. Czysta logika — bez dostępu do stanu formularza.
 */

import type { TFunction } from 'i18next'

import { ApiError } from '../../../api/envelope'
import { errorText } from '../../../lib/errorText'
import type { Model } from '../../chats/modelsQuery'

/** Nazwy modeli danego typu plus bieżąca wartość pola, żeby nie wypadła z listy wyboru. */
export function modelNames(models: readonly Model[], modelType: string, current: string): string[] {
  const names = models
    .filter((model) => model.model_type.includes(modelType))
    .map((model) => model.name)
  const unique = [...new Set(names)]
  if (current !== '' && !unique.includes(current)) unique.unshift(current)
  return unique
}

/**
 * Komunikat błędu mutacji (T3b): treść z `ApiError` tłumaczona wg INVENTORY
 * (`errorText`), a przy błędzie transportu — tekst z i18n.
 */
export function mutationMessage(error: unknown, fallback: string, t: TFunction): string {
  return error instanceof ApiError && error.message !== '' ? errorText(error, t) : fallback
}

/** Separator w podglądzie: znaki sterujące pokazujemy dosłownie (`\n`, `\t`). */
export function escapedDelimiter(delimiter: string): string {
  return delimiter.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/\t/g, '\\t')
}

/**
 * Powód nieaktywnego „Zapisz” (SC-V12-08): brak zmian albo błąd pól metadanych (problem z
 * kluczem wiersza). Błędy pól tekstowych NIE wyłączają przycisku (U11) — ujawnia je klik,
 * więc wtedy powodu nie ma. Tekst „brak zmian” jest wspólny dla wszystkich szuflad
 * (`common.noChangesToSave`, SC-V13-11 — DEC-372).
 */
export function configSaveReason(
  t: TFunction,
  patchEmpty: boolean,
  metaHasError: boolean,
): string | null {
  if (patchEmpty) return t('common.noChangesToSave')
  if (metaHasError) {
    return t('datasets.config.reason.fixField', { field: t('datasets.config.metadata.key') })
  }
  return null
}
