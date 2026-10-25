// Pomocnik drag & drop dla scenariuszy e2e (kontrakt WP E5-H3 §„Plan testów", usterka #5):
// upuszczenie pliku z prawdziwym `DataTransfer` — `File` powstaje w kontekście strony z bajtów
// przekazanych z Node, a zdarzenia `dragenter`/`dragover`/`drop` lecą na element strefy.
// `setInputFiles` jest tu zabronione, bo omija ścieżkę `drop`. `DataTransfer` można skonstruować
// tylko w Chromium i Firefoksie (Playwright `dispatchEvent` — `JSHandle` jako wartość pola).
import type { Locator, Page } from '@playwright/test'

/** Argumenty do `evaluateHandle` — `Buffer` nie przechodzi przez most, więc idzie tablica liczb. */
type DropInit = { data: number[]; name: string; mime: string }

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
      const file = new File([new Uint8Array(init.data)], init.name, { type: init.mime })
      const transfer = new DataTransfer()
      transfer.items.add(file)
      return transfer
    },
    { data: [...bytes], name, mime } satisfies DropInit,
  )

  await locator.dispatchEvent('dragenter', { dataTransfer })
  await locator.dispatchEvent('dragover', { dataTransfer })
  await locator.dispatchEvent('drop', { dataTransfer })
}
