/**
 * Czysta logika formularza modelu (kontrakt WP E5-H8c §1, K13 „Poprawka 2026-10-10”):
 * walidacja okna kontekstu i równoległych zapytań oraz budowa ciała PATCH z PEŁNYM `extra`
 * odczytanym z modelu i podmienionym/usuniętym kluczem `max_concurrency`. Bez zależności —
 * backend waliduje zakres, UI tylko podpowiada błąd przed zapisem.
 */

/** Najmniejsze dopuszczalne okno kontekstu (tokeny) — kontrakt §1. */
export const MIN_CONTEXT_WINDOW = 1024

/** Zakres `extra.max_concurrency` (K13 „Poprawka 2026-10-10” p. 1): liczba całkowita 1–32. */
export const CONCURRENCY_MIN = 1
export const CONCURRENCY_MAX = 32

/** Domyślne równoległości, gdy klucza brak (K13 p. 2) — wartość placeholdera pola. */
export const CONCURRENCY_DEFAULTS: Record<string, number> = {
  vision: 3,
  image2text: 3,
  embedding: 4,
}

/** Typy modeli, dla których pole „Równoległe zapytania” ma sens (kontrakt §1). */
const CONCURRENCY_MODEL_TYPES = ['vision', 'image2text', 'embedding']

/** Czy dla danego typu modelu pokazujemy pole współbieżności (kontrakt §1). */
export function supportsConcurrency(modelType: string): boolean {
  return CONCURRENCY_MODEL_TYPES.includes(modelType)
}

/**
 * Walidacja okna kontekstu: puste i nieliczbowe → `invalid`, liczba całkowita poniżej
 * `MIN_CONTEXT_WINDOW` → `min`, w przeciwnym razie `null` (poprawne).
 */
export function validateMaxTokens(value: string): 'min' | 'invalid' | null {
  const trimmed = value.trim()
  if (!/^\d+$/.test(trimmed)) {
    return 'invalid'
  }
  return Number(trimmed) < MIN_CONTEXT_WINDOW ? 'min' : null
}

/**
 * Walidacja równoległości: puste (białe znaki też) → `null` (domyślne), liczba całkowita 1–32 →
 * `null`, każda inna wartość (w tym poza zakresem, ułamek, tekst, ujemna) → `range`.
 */
export function validateConcurrency(value: string): 'range' | null {
  const trimmed = value.trim()
  if (trimmed === '') {
    return null
  }
  if (!/^\d+$/.test(trimmed)) {
    return 'range'
  }
  const parsed = Number(trimmed)
  return parsed < CONCURRENCY_MIN || parsed > CONCURRENCY_MAX ? 'range' : null
}

/**
 * Ciało `PATCH …/models/{id}`: `max_tokens` jako liczba plus PEŁNE `extra` z modelu
 * (nie gubimy `supports_reasoning`, `extra_body` itd.). Dla typów obsługujących współbieżność
 * ustawiamy `max_concurrency` na liczbę, a puste pole usuwa klucz; dla pozostałych typów `extra`
 * zostaje bez zmian. Wejściowe `extra` nie jest mutowane — pracujemy na kopii.
 */
export function buildModelPatch(
  model: { extra: Record<string, unknown>; model_type: string },
  input: { maxTokens: string; concurrency: string },
): { max_tokens: number; extra: Record<string, unknown> } {
  const extra = { ...model.extra }
  if (supportsConcurrency(model.model_type)) {
    const concurrency = input.concurrency.trim()
    if (concurrency === '') {
      delete extra.max_concurrency
    } else {
      extra.max_concurrency = Number(concurrency)
    }
  }
  return { max_tokens: Number(input.maxTokens.trim()), extra }
}
