/**
 * Tekst błędu API do wyświetlenia (WP V12-2 T3b; wspólny wzorzec `mutationMessage`):
 * komunikat serwera z koperty RAGFlow (kod 101/102/500) tłumaczony przez
 * `translateServerMessage` wg INVENTORY (K20 §5; work/wp/V12-2/INVENTORY.md) — tłumaczenie
 * dzieje się w chwili renderu, więc działa też po zmianie języka. Błędy bez koperty
 * (transport, sesja) i obce błędy — bez zmian (INVENTORY: „nieznany tekst → dosłownie”).
 */
import type { TFunction } from 'i18next'

import { ApiError } from '../api/envelope'

import { translateServerMessage } from './serverMessages'

export function errorText(error: unknown, t: TFunction): string {
  if (error instanceof ApiError) return translateServerMessage(error.code, error.message, t)
  return error instanceof Error && error.message !== '' ? error.message : String(error)
}
