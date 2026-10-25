// Scenariusz pierwszego użytkownika na czystej instalacji (K1 poprawka 2026-10-04 p. 1, WP E5-H1 T3).
// Stos produkcyjny + nakładka fake-llm stawia tools/dev/clean-install.sh; ten jeden test przechodzi
// pięć kroków: /health/ready, logowanie formularzem, utworzenie datasetu domyślnym modelem, upload
// i sparsowanie sample.pdf oraz test retrievalu. Brak seedu K9 — konto pochodzi z WD_ADMIN_*.
// Selektory jak użytkownik: role/etykiety/tekst (bez data-testid).
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''

// Ścieżka bezwzględna próbki liczona względem pliku spec (brief T3); `setInputFiles` nie przyjmuje
// ścieżek względnych. Projekt jest ESM (`__dirname` nie istnieje) — wzorzec `import.meta.url`
// jak w `frontend/e2e/s03-upload-parse.spec.ts`.
const SAMPLE_PDF = fileURLToPath(new URL('../e2e/fixtures/sample.pdf', import.meta.url))

const DATASET_NAME = 'Clean install e2e'
// Zapytanie o treść sample.pdf (nagłówek i pierwszy akapit dokumentu: „Zamek Królewski na Wawelu”).
const QUESTION = 'Zamek Królewski na Wawelu'

test('clean-install: logowanie, dataset domyślnym modelem, upload PDF, retrieval', async ({
  page,
  request,
}) => {
  // 1. API żyje: /health/ready przez reverse proxy kontenera `web`.
  const health = await request.get('/health/ready')
  expect(health.status(), 'GET /health/ready').toBe(200)

  // 2. Logowanie formularzem `/login` kontem administracyjnym czystej instalacji.
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL)
  // `exact` — inaczej `getByLabel('Hasło')` trafia też w przycisk „Pokaż hasło”
  // (aria-label z prefiksem), co daje strict mode violation.
  await page.getByLabel('Hasło', { exact: true }).fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Zaloguj się' }).click()
  const nav = page.getByRole('navigation')
  await expect(nav.getByRole('link', { name: 'Bazy wiedzy' })).toBeVisible()

  // 3. Utworzenie datasetu w UI BEZ zmiany modelu — obowiązuje domyślny embedding instancji
  //    (pole jest wypełnione samo); podajemy tylko nazwę.
  await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
  await page.getByRole('button', { name: 'Utwórz dataset' }).first().click()
  const createDialog = page.getByRole('dialog')
  await expect(createDialog).toBeVisible()
  await createDialog.getByLabel('Nazwa').fill(DATASET_NAME)
  await createDialog.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()

  // 4. Upload sample.pdf z domyślnym „Parsuj po przesłaniu” (przełącznik włączony z założenia).
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

  // Sparsowanie do stanu „Sukces”/„Success” — wiersz dokumentu w siatce plików (timeout 240 s).
  const row = page.getByRole('row').filter({ hasText: 'sample.pdf' })
  await expect(row).toContainText(/Sukces|Success/, { timeout: 240_000 })

  // 5. Test retrievalu zwraca co najmniej jedno trafienie (nagłówek „Łącznie N”).
  await page.getByRole('tab', { name: 'Test retrievalu' }).click()
  await page.getByLabel('Pytanie').fill(QUESTION)
  await page.getByRole('button', { name: 'Uruchom' }).click()
  const total = page.getByText(/Łącznie \d+/)
  await expect(total).toBeVisible({ timeout: 60_000 })
  const hitCount = Number((await total.innerText()).replace(/\D/g, ''))
  expect(hitCount, 'liczba trafień testu retrievalu').toBeGreaterThanOrEqual(1)
})
