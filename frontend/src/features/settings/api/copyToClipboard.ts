/**
 * Kopiowanie do schowka z fallbackiem dla niezabezpieczonego kontekstu (defekt MAJOR z
 * QA-UI E6-2-1): `navigator.clipboard` istnieje tylko w secure context (HTTPS/localhost) —
 * na HTTP klik „Kopiuj" w kartach ustawień rzucał TypeError bez żadnego odzewu. Funkcja
 * zwraca `true`/`false` i nigdy nie rzuca; komponent pokazuje „Skopiowano" wyłącznie przy
 * `true`, a przy `false` czytelny komunikat i zaznaczony tekst (patrz `selectElementContents`).
 */

/** Fallback: ukryta `textarea` + `document.execCommand('copy')` — stare API, ale jedyne
 *  działające bez secure context. Zwraca `false`, gdy przeglądarka odmówi. */
function copyViaExecCommand(text: string): boolean {
  const textarea = document.createElement('textarea')
  textarea.value = text
  // Poza ekranem, ale renderowana: treść `display:none` nie daje się zaznaczyć.
  textarea.style.position = 'fixed'
  textarea.style.top = '-1000px'
  // Focus trap dialogu MUI przechwytuje fokus elementów poza `[role="dialog"]` (defekt MAJOR
  // z QA-UI E6-2-2): textarea przy `document.body` traciła fokus i zaznaczenie, zanim zadziałał
  // `execCommand('copy')` — schowek dostawał pusty tekst, a UI pokazywał „Skopiowano”.
  // Doklejamy więc tekstarkę WEWNĄTRZ otwartego dialogu; poza dialogiem — do body jak dotychczas.
  const active = document.activeElement
  const host = active?.closest('[role="dialog"]') ?? document.body
  // Fokus sprzed tekstarki wraca na miejsce po kopiowaniu (klawiatura nie gubi pozycji).
  const previous = active instanceof HTMLElement ? active : null
  host.appendChild(textarea)
  // `readonly` PO wstawieniu (kolejność wg briefu): iOS Safari nie wysuwa klawiatury,
  // a wartość jest już ustawiona.
  textarea.setAttribute('readonly', '')
  textarea.focus()
  textarea.select()
  // Pewniak pełnego zaznaczenia: `select()` nie zawodzi, ale zakres pilnujemy wprost.
  textarea.setSelectionRange(0, text.length)
  let copied = false
  try {
    copied = document.execCommand('copy') === true
  } catch {
    // Kontrakt „nigdy nie rzuca”: środowisko bez `execCommand` (np. jsdom) to porażka
    // kopiowania, nie błąd aplikacji.
  }
  textarea.remove()
  previous?.focus()
  return copied
}

/** Kopiuje tekst do schowka: API asynchroniczne, gdy dostępne (secure context), inaczej
 *  fallback `execCommand`. Zwraca sukces; nigdy nie rzuca. */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator.clipboard?.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Schowek odrzucił zapis (np. brak zgody) — próba fallbacku nic nie kosztuje.
    }
  }
  return copyViaExecCommand(text)
}

/** Zaznacza całą treść elementu (blok przykładu, adres) na potrzeby ręcznego kopiowania
 *  po porażce: użytkownik naciska Ctrl+C i dostaje dokładnie ten tekst. */
export function selectElementContents(element: HTMLElement | null): void {
  if (element === null) return
  const selection = document.getSelection()
  if (selection === null) return
  const range = document.createRange()
  range.selectNodeContents(element)
  selection.removeAllRanges()
  selection.addRange(range)
}
