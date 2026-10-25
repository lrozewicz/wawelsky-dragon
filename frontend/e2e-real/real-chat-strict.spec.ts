// Czat na stosie z domyślnym modelem `fake-chat-strict` (usterka #6 z testu v1; K10 poprawka
// 2026-10-04; kontrakt WP E5-H5 §4). Model strict odrzuca kary oraz `temperature`/`top_p` ≠ 1
// kodem 400 — backend musi ponowić żądanie bez tych parametrów (backend/app/llm/param_retry.py),
// inaczej czat kończy się w UI błędem „LLM bad request”. Scenariusz przechodzi jak użytkownik:
// logowanie formularzem, dataset domyślnym modelem, upload i parsowanie sample.pdf, asystent na
// tym datasecie (model w formularzu NIE zmieniany — obowiązuje domyślny strict), pytanie i odpowiedź.
// Selektory: role/etykiety/tekst (bez data-testid, bez `test/reset`, bez SQL); bez `waitForTimeout`.
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''

// Ścieżka bezwzględna próbki liczona względem pliku spec (ESM, `__dirname` nie istnieje).
const SAMPLE_PDF = fileURLToPath(new URL('../e2e/fixtures/sample.pdf', import.meta.url))

const DATASET_NAME = 'Strict chat'
const CHAT_NAME = 'Strict'
const QUESTION = 'O czym jest dokument?'
// Prompt systemowy z placeholderem `{knowledge}` — bez niego walidacja blokuje zapis bazy wiedzy
// (chat.settings.systemKnowledge w locale pl / frontend/src/features/chats/settings/schema.ts).
const SYSTEM_PROMPT = 'Odpowiadaj na podstawie przekazanej wiedzy.\n\n{knowledge}'

// Deterministyczna treść fake-llm (K10 §4): blok wiedzy → „Na podstawie źródeł: …”, a bez trafienia
// retrievalu → „Odpowiedź testowa: <pytanie>”. Dymek z błędem 400 zostaje pusty (sam Alert), więc
// dopasowanie tej treści dowodzi NIEPUSTEJ odpowiedzi asystenta, a nie komunikatu błędu.
const ANSWER = /Na podstawie źródeł|Odpowiedź testowa/

/** Logowanie formularzem `/login` kontem administracyjnym czystej instalacji (wzorzec clean-install.spec.ts). */
async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL)
  // `exact` — inaczej `getByLabel('Hasło')` trafia też w przycisk „Pokaż hasło”.
  await page.getByLabel('Hasło', { exact: true }).fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Zaloguj się' }).click()
  await expect(
    page.getByRole('navigation').getByRole('link', { name: 'Bazy wiedzy' }),
  ).toBeVisible()
}

test('real-chat-strict: czat na domyślnym modelu strict odpowiada bez „bad request”', async ({
  page,
}) => {
  test.setTimeout(600_000)
  await loginAsAdmin(page)
  const nav = page.getByRole('navigation')

  // 1. Domyślny model czatu stosu to naprawdę strict. Karta „Modele domyślne” na
  //    /user-setting/model pokazuje nazwę domyślnego LLM z GET /users/me/models — na stosie B
  //    (WD_CI_DEFAULT_CHAT=fake-chat-strict) wybrana pozycja to `fake-chat-strict`. Wejście
  //    linkiem w menu (nie `page.goto`) — stos produkcyjny ma ciasteczko odświeżania z flagą
  //    Secure, więc twarde przeładowanie po HTTP gubi sesję (K8).
  await nav.getByRole('link', { name: 'Ustawienia' }).click()
  await expect(page).toHaveURL(/\/user-setting\/model$/)
  await expect(page.getByRole('combobox', { name: 'Model LLM' })).toContainText('fake-chat-strict')

  // 2. Dataset domyślnym modelem instancji (pole embeddingu wypełnia się samo — tylko nazwa).
  await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
  await page.getByRole('button', { name: 'Utwórz dataset' }).first().click()
  const createDataset = page.getByRole('dialog')
  await expect(createDataset).toBeVisible()
  await createDataset.getByLabel('Nazwa').fill(DATASET_NAME)
  await createDataset.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()

  // 3. Upload sample.pdf z domyślnym „Parsuj po przesłaniu” i parsowanie do „Sukces” (≤ 240 s).
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  await expect(uploadDialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  const chooser = page.waitForEvent('filechooser')
  await uploadDialog.getByRole('button', { name: 'Wybierz pliki' }).click()
  await (await chooser).setFiles(SAMPLE_PDF)
  await uploadDialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect(uploadDialog.getByText('Przesłano', { exact: true })).toBeVisible({
    timeout: 60_000,
  })
  await uploadDialog.getByRole('button', { name: 'Gotowe' }).click()
  const row = page.getByRole('row').filter({ hasText: 'sample.pdf' })
  await expect(row).toContainText(/Sukces|Success/, { timeout: 240_000 })

  // 4. Asystent: utworzenie czatu samą nazwą (→ `/chat/:id`); model pozostaje domyślny (strict).
  await nav.getByRole('link', { name: 'Czat' }).click()
  await expect(page).toHaveURL(/\/chats$/)
  await page.getByRole('button', { name: 'Utwórz czat' }).first().click()
  const createChat = page.getByRole('dialog')
  await createChat.getByLabel('Nazwa').fill(CHAT_NAME)
  await createChat.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page).toHaveURL(/\/chat\/[^/]+$/)

  // 5. Baza wiedzy w zakładce „Asystent” + prompt systemowy z `{knowledge}`; modelu nie ruszamy.
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  await page.getByRole('combobox', { name: 'Bazy wiedzy' }).click()
  await page.getByRole('option', { name: DATASET_NAME }).click()
  // Pytanie „O czym jest dokument?” nie trafia w żaden chunk (zmierzone: retrieval zwraca 0 trafień),
  // a przy niepustym „Odpowiedź przy braku wyników” backend pomija wołanie LLM (chat_pipeline:
  // ścieżka empty_response) — wtedy usterka #6 w ogóle nie jest dotykana. Czyszcząc to pole wymuszamy
  // realne wywołanie modelu strict (odpowiedź to blok wiedzy albo fallback „Odpowiedź testowa: …”).
  await page.getByLabel('Odpowiedź przy braku wyników').fill('')
  await page.getByRole('tab', { name: 'Silnik promptu' }).click()
  await page.getByLabel('Prompt systemowy').fill(SYSTEM_PROMPT)
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()

  // 6. Pytanie i odpowiedź: niepusty dymek asystenta (≤ 60 s). Na kodzie z usterką #6 (bez
  //    param_retry) model strict zwraca 400 i w miejscu treści pojawia się Alert „LLM bad request”.
  await page.getByPlaceholder('Wpisz pytanie…').fill(QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()
  const answer = page.getByRole('article', { name: 'Odpowiedź asystenta' }).last()
  await expect(answer).toContainText(ANSWER, { timeout: 60_000 })
  // Koniec streamu: przycisk wraca do „Wyślij” (w trakcie jest „Zatrzymaj”).
  await expect(page.getByRole('button', { name: 'Wyślij' })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText(/bad request/i)).toHaveCount(0)
})
