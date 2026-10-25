/**
 * Pomocnik drag & drop dla wyroczni realnej (kopia `frontend/e2e/helpers/dnd.ts`, WP E5-H5 T2a;
 * kontrakt §4 zabrania importu z `e2e/`). Upuszczenie pliku z prawdziwym `DataTransfer` — `File`
 * powstaje w kontekście strony, a zdarzenia `dragenter`/`dragover`/`drop` lecą na element strefy.
 * `setInputFiles` jest tu zabronione, bo omija ścieżkę `drop`.
 *
 * Różnica względem oryginału: bajty idą przez most `evaluateHandle` jako **base64** (`init.data:
 * string`), nie tablica liczb — pliki korpusu mają kilka–kilkanaście MB i tablica liczb byłaby
 * zbyt duża dla protokołu Playwrighta. Dekodowanie po stronie przeglądarki: `atob` → `Uint8Array`.
 */
import type { Locator, Page } from '@playwright/test'

/** Argumenty do `evaluateHandle` — bajty jako base64 (patrz nagłówek). */
type DropInit = { data: string; name: string; mime: string }

/**
 * Upuszcza plik o danych bajtach na `locator`. Sekwencja `dragenter` → `dragover` → `drop` z tym
 * samym `DataTransfer` (jak realne przeciągnięcie; bez `dragover` przeglądarka nie dopuszcza `drop`).
 */
export async function dropFile(
  page: Page,
  locator: Locator,
  bytes: Buffer,
  name: string,
  mime: string,
): Promise<void> {
  const dataTransfer = await page.evaluateHandle(
    (init: DropInit) => {
      const binary = atob(init.data)
      const data = Uint8Array.from(binary, (char) => char.charCodeAt(0))
      const file = new File([data], init.name, { type: init.mime })
      const transfer = new DataTransfer()
      transfer.items.add(file)
      return transfer
    },
    { data: bytes.toString('base64'), name, mime } satisfies DropInit,
  )

  await locator.dispatchEvent('dragenter', { dataTransfer })
  await locator.dispatchEvent('dragover', { dataTransfer })
  await locator.dispatchEvent('drop', { dataTransfer })
}
