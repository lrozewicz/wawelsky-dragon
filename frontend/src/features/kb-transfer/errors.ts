/**
 * Mapowanie `error.code` z K19 §3 na klucz i18n (kontrakt WP E7-2 §7/§2).
 * Slugi: tabela kodów HTTP §3 oraz błędy walidacji paczki §3/§5 (`state=invalid`,
 * `WdTask.error.code`). Nieznany kod dostaje tekst ogólny.
 */

/** Slugi błędów K19 — dla każdego z nich istnieje klucz `kbTransfer.error.<slug>`. */
export const KB_ERROR_SLUGS: readonly string[] = [
  // Tabela kodów HTTP (K19 §3).
  'validation_failed',
  'forbidden',
  'invalid_signature',
  'not_found',
  'export_in_progress',
  'offset_mismatch',
  'import_not_ready',
  'name_conflict',
  'embedding_model_required',
  'embedding_model_unknown',
  'export_expired',
  'package_too_large',
  // Błędy walidacji paczki (K19 §3, komunikaty `DatasetImport.errors[]` i `WdTask.error`;
  // `not_a_package` dopisany K20 §2).
  'not_a_package',
  'invalid_archive',
  'manifest_invalid',
  'schema_too_new',
  'unsafe_path',
  'archive_too_large',
  'checksum_mismatch',
  'missing_entry',
  'unexpected_entry',
  'dimension_mismatch',
]

/** Klucz i18n komunikatu dla kodu błędu: `kbTransfer.error.<slug>`, inaczej `kbTransfer.error.unknown`. */
export function kbErrorMessageKey(code: string): string {
  return KB_ERROR_SLUGS.includes(code) ? `kbTransfer.error.${code}` : 'kbTransfer.error.unknown'
}

/**
 * Klucz i18n dla błędu walidacji paczki (`DatasetImport.errors[]`), gdy komunikat API jest
 * mylący albo ma techniczny ogon; `null` = pokaż komunikat z API. Mapowanie WYŁĄCZNIE po `code`
 * (K20 §2, SC-V12-02): backend sam rozróżnia `not_a_package` (brak `manifest.json`), a
 * `unexpected_entry`/`unsafe_path` niosą w komunikacie nazwę wpisu — te zostaje z API.
 */
export function kbPackageErrorOverrideKey(error: { code: string; message: string }): string | null {
  if (error.code === 'invalid_archive') return 'kbTransfer.error.invalid_archive'
  if (error.code === 'not_a_package') return 'kbTransfer.error.not_a_package'
  return null
}

/**
 * Tekst Alertu fazy `invalid` (SC-V12-06 k.4, K20 §5 p. 2, QA V12-2-1 D1): błąd z override →
 * tekst z i18n; EN bez override → przyczyna po `code` z locale (polski komunikat serwera
 * trafia do zwiniętego bloku szczegółów); PL bez override → komunikat API (bez zmian).
 */
export function kbPackageAlertText(
  error: { code: string; message: string },
  isEnglish: boolean,
  t: (key: string) => string,
): string {
  const overrideKey = kbPackageErrorOverrideKey(error)
  if (overrideKey !== null) return t(overrideKey)
  return isEnglish ? t(kbErrorMessageKey(error.code)) : error.message
}

/** Czy pokazać zwinięty blok szczegółów serwera: tylko EN i błędy bez override (D1). */
export function kbShowServerDetails(
  error: { code: string; message: string },
  isEnglish: boolean,
): boolean {
  return isEnglish && kbPackageErrorOverrideKey(error) === null
}
