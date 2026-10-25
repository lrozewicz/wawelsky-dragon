/**
 * Oczekiwane stany dokumentów korpusu PL (CONTRACT WP E5-H5 §5 + addendum §10; brief T2b p. 1).
 * Źródło listy formatów: `backend/app/parsing/registry.py` (REGISTRY) — nie zgadujemy.
 *
 * `success` — konwerter istnieje i plik parsuje się do „Sukces”.
 * `readable-error` — brak konwertera; UI musi pokazać stan „Błąd” z czytelnym powodem
 * pasującym do `ERROR_PATTERN`. Powód nieczytelny albo jego brak = czerwony test (usterka aplikacji).
 *   Odrzut już przy uploadzie (stan „Błąd przesyłania”): dawniej UI nie pokazywał przyczyny, więc
 *   test dopisywał adnotację `usterka-ux`. Od E5-H6a dialog uploadu pokazuje powód odrzutu z koperty
 *   API, więc adnotacja nie występuje — `.odp` jest twardą asercją (`real-corpus.spec.ts`).
 * `success-or-readable-error` — konwerter istnieje, ale w tym stosie może się nie wykonać (brak
 * programu binarnego w workerze); akceptujemy „Sukces” albo „Błąd” z przyczyną pasującą do
 * `BINARY_MISSING_PATTERN`. Każda inna przyczyna błędu to nadal czerwono.
 *
 * Rozszerzenie spoza tabeli = czerwony test z nazwą pliku (korpus się zmienił — uzupełnij tabelę).
 */

export type ExpectedStatus = 'success' | 'readable-error' | 'success-or-readable-error'

/** Rozszerzenie (bez kropki, małymi literami) → oczekiwany stan końcowy dokumentu. */
export const EXPECTED: Record<string, ExpectedStatus> = {
  // success — REGISTRY ma konwerter dla każdego z tych formatów.
  pdf: 'success',
  docx: 'success',
  xlsx: 'success',
  xls: 'success',
  csv: 'success',
  pptx: 'success',
  md: 'success',
  txt: 'success',
  eml: 'success',
  html: 'success',
  // Addendum §10 (zmierzone T2a 2026-10-04): w domyślnym workerze (worker-ocr nie jest włączony)
  // konwersja `.doc` kończy się „Błąd” — „BinaryMissing: Required program 'wvHtml' is not installed;
  // use the worker-ocr image”. To udokumentowane ograniczenie v1 (worker bez OCR/wv), nie usterka
  // aplikacji: akceptujemy „Sukces” albo „Błąd” z przyczyną braku binarki. To samo dotyczy `ppt`
  // (brak w korpusie, ale ta sama ścieżka konwertera).
  doc: 'success-or-readable-error',
  ppt: 'success-or-readable-error',
  // readable-error — brak wpisu w REGISTRY → `unsupported_format(".odp"/".epub")`.
  odp: 'readable-error',
  epub: 'readable-error',
  // zmierzone 2026-10-04 (bieg T2a na stosie clean-install): „Sukces”, 1 chunk (fake-vision opisuje obraz).
  jpg: 'success',
}

/** Czytelny powód braku konwertera (CONTRACT §5). */
export const ERROR_PATTERN = /Unsupported file format|Nieobsługiwany format/i

/** Powód braku programu konwertera w workerze (CONTRACT §10, zmierzone T2a). */
export const BINARY_MISSING_PATTERN = /not installed|worker-ocr/i

/**
 * Minimalna liczba chunków per nazwa pliku (WP E5-H6d T4, raport
 * `work/wp/E5-H6d/reports/pptx-before-after.md`, zmierzone na tym korpusie).
 * Źródło wartości: poprawki PPTX DEC-263 (`<h2>Slajd N</h2>` — granica chunka dla presetu
 * `naive`) i DEC-264 (obrazy slajdów powyżej progu do OCR/VLM). Wartości zależą od
 * `chunk_token_num = 512` (domyślny `DEFAULT_PARSER_CONFIG`) — przy innym limicie sprawdź ponownie.
 * Tylko pliki wymienione tutaj podlegają asercji progu (reszta korpusu bez zmian).
 */
export const MIN_CHUNKS: Record<string, number> = {
  'strategia_cyfryzacji_nowe_technologie_ai.pptx': 5,
  'witaminy_c_i_d.pptx': 2,
}
