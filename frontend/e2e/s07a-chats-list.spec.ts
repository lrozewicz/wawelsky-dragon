// Scenariusz S7a (brief E3-5a T6): pusty stan listy czatów → utworzenie czatu → przejście na
// `/chat/:id` → zębatka i zmiana opisu w szufladzie → F5 z zachowanym opisem → powrót na listę →
// usunięcie czatu. Strażnik błędów konsoli/pageerror jest w fixture (e2e/fixtures.ts) — działa
// w teardownie, więc scenariusz nie może zostawić po sobie ani jednego błędu w konsoli.
import { ADMIN_EMAIL, ADMIN_PASSWORD, expect, test } from './fixtures'
import { expectNoSeriousA11y } from './helpers/axe'

const CHAT_NAME = 'E2E czat'
const CHAT_DESCRIPTION = 'opis e2e'

test('S7a: czat z listy, ustawienia na /chat/:id i usunięcie', async ({ page }) => {
  // 1. Logowanie kontem z seedu K9 przez UI (jak S6-01).
  await page.goto('/')
  await page.getByTestId('login-email').fill(ADMIN_EMAIL)
  await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('home-banner')).toBeVisible()

  // 2. Reset przed biegiem nie zasiewa czatów — lista startuje pusta.
  const nav = page.getByRole('navigation')
  await nav.getByRole('link', { name: 'Czat' }).click()
  await expect(page).toHaveURL(/\/chats$/)
  const empty = page.getByTestId('empty-state')
  await expect(empty).toContainText('Nie masz jeszcze czatów')

  // 3. „Utwórz czat” z pustego stanu (to samo słowo jest w nagłówku strony) → sama nazwa →
  //    przejście na `/chat/:id` z nagłówkiem z nazwą czatu.
  await empty.getByRole('button', { name: 'Utwórz czat' }).click()
  const createDialog = page.getByRole('dialog')
  await createDialog.getByLabel(/Nazwa/).fill(CHAT_NAME)
  await createDialog.getByRole('button', { name: 'Utwórz' }).click()

  await expect(page).toHaveURL(/\/chat\/[^/]+$/)
  await expect(page.getByRole('heading', { name: CHAT_NAME })).toBeVisible()

  // Główny ekran scenariusza: strona czatu tuż po utworzeniu (jasny motyw).
  await expectNoSeriousA11y(page, 'S7a czat')

  // 4. Zębatka otwiera szufladę; opis zmieniamy w zakładce „Asystent”, zapis ją zamyka.
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  await page.getByLabel('Opis').fill(CHAT_DESCRIPTION)
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()

  // 5. F5 na `/chat/:id` — opis wraca z backendu (PATCH zapisał go po stronie serwera).
  await page.reload()
  await expect(page.getByRole('heading', { name: CHAT_NAME })).toBeVisible()
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await expect(page.getByLabel('Opis')).toHaveValue(CHAT_DESCRIPTION)
  await page.getByRole('button', { name: 'Anuluj' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()

  // 6. Powrót na listę i usunięcie czatu z menu karty; lista wraca do pustego stanu.
  await nav.getByRole('link', { name: 'Czat' }).click()
  await expect(page.getByTestId('chat-card')).toContainText(CHAT_NAME)
  await page.getByRole('button', { name: `Menu czatu ${CHAT_NAME}` }).click()
  await page.getByRole('menuitem', { name: 'Usuń' }).click()
  const deleteDialog = page.getByRole('dialog')
  await expect(deleteDialog).toContainText(`Czy usunąć czat „${CHAT_NAME}”?`)
  await deleteDialog.getByRole('button', { name: 'Usuń' }).click()
  await expect(page.getByTestId('empty-state')).toContainText('Nie masz jeszcze czatów')
})
