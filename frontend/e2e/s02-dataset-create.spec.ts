// Scenariusz S6-02 (08 §11.2, kontrakt WP E3-3a §T6): utworzenie datasetu z pustego stanu listy
// baz wiedzy — nazwa + domyślny model embeddingu + metoda General, lądowanie na `/dataset/files/:id`
// z nagłówkiem datasetu, a po powrocie karta jest widoczna na liście (`/datasets`) i na Home (`/`).
// Strażnik błędów konsoli/pageerror jest w fixture (e2e/fixtures.ts) — działa w teardownie.
import { ADMIN_EMAIL, ADMIN_PASSWORD, expect, resetDb, test } from './fixtures'
import { expectNoSeriousA11y } from './helpers/axe'

const DATASET_NAME = 'E2E S6-02 baza'
// Domyślny model embeddingu z seedu K9 (`fake-embed-1024` jest `is_default`), który dialog
// podpowiada z `GET /users/me/models` — pole ma być wypełnione bez wybierania czegokolwiek.
const DEFAULT_EMBEDDING = 'fake-embed-1024'

test('S6-02: utworzenie datasetu z pustego stanu; karta na liście i na Home', async ({
  page,
  request,
}) => {
  // Reset daje pusty stan listy niezależnie od tego, co zostawiły po sobie wcześniejsze pliki
  // biegu (K9 czyści bazę i storage).
  await resetDb(request)

  // 1. Logowanie kontem z seedu K9 przez UI (jak S6-01 i S7a).
  await page.goto('/')
  await page.getByTestId('login-email').fill(ADMIN_EMAIL)
  await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('home-banner')).toBeVisible()

  // 2. Lista baz wiedzy startuje z pustym stanem (reset nie zasiewa datasetów).
  const nav = page.getByRole('navigation')
  await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
  const empty = page.getByTestId('empty-state')
  await expect(empty).toContainText('Nie masz jeszcze baz wiedzy')

  // 3. „Utwórz dataset” z pustego stanu: nazwa, domyślny embedding i metoda General (obie
  //    podpowiedziane) — formularz nie wymaga wybierania niczego poza nazwą.
  await empty.getByRole('button', { name: 'Utwórz dataset' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Nazwa').fill(DATASET_NAME)
  await expect(dialog.getByRole('combobox', { name: 'Model embeddingu' })).toHaveValue(
    DEFAULT_EMBEDDING,
  )
  await expect(dialog.getByRole('combobox', { name: 'Metoda chunkowania' })).toContainText(
    'General',
  )
  await dialog.getByRole('button', { name: 'Utwórz' }).click()

  // 4. Po `POST /datasets` adres przechodzi na zakładkę Pliki nowego datasetu, a nagłówek
  //    szczegółu niesie jego nazwę.
  await expect(page).toHaveURL(/\/dataset\/files\/[^/]+$/)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()

  // Główny ekran scenariusza: pliki nowego datasetu z pustym stanem (jasny motyw).
  await expectNoSeriousA11y(page, 'S6-02 pliki datasetu')

  // 5. Powrót na listę — karta nowego datasetu jest widoczna.
  await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
  await expect(page.getByTestId('dataset-card')).toContainText(DATASET_NAME)

  // 6. Karta jest też w sekcji „Bazy wiedzy” na Home (ostatnio zmienione).
  await nav.getByRole('link', { name: 'Start' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByTestId('home-section-datasets')).toContainText(DATASET_NAME)
})
