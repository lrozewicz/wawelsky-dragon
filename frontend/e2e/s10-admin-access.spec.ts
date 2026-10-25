// Scenariusz S6-10 (08-frontend §11.2, brief WP E3-6c2/T7, rozszerzony w WP E3-H2b §C5): admin
// zakłada użytkownika, tworzy mu klucz API z datą wygaśnięcia i nadaje dostęp do jednego z dwóch
// czatów; zalogowany użytkownik widzi tylko udostępniony czat, nie ma pozycji „Administracja"
// w menu, a przełączone ręcznie tryb ciemny i język EN przeżywają przeładowanie strony. Błędów
// konsoli pilnuje fixture `page` (`./fixtures`); drugi kontekst przeglądarki dostaje własny nasłuch
// (`watchConsoleErrors`) z tym samym filtrem. Sprzątanie (czaty i konto) jest w `finally`, żeby
// awaria w środku scenariusza nie zostawiła danych na stosie.
import type { Response } from '@playwright/test'

import { expect, test } from './fixtures'
import { expectNoSeriousA11y } from './helpers/axe'
import { apiLogin, createChat, deleteAllChats, loginViaUi } from './helpers'
import {
  createUserViaUi,
  deleteUserByEmail,
  grantAccessViaUi,
  loginViaUiAs,
  openUserKeysDialog,
  watchConsoleErrors,
} from './helpers/admin'

const CHAT_A = 'S10 czat A'
const CHAT_B = 'S10 czat B'
const USER_PASSWORD = 'wd-test-user-1'
const KEY_NAME = 'S10 klucz'

/** Jutro (ta sama pora) w formacie pola `datetime-local`: `YYYY-MM-DDTHH:mm`. */
function tomorrowLocal(): string {
  const date = new Date(Date.now() + 24 * 60 * 60 * 1000)
  const pad = (value: number): string => String(value).padStart(2, '0')
  const day = `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  return `${day}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** Nazwy czatów z odpowiedzi `GET /api/v1/chats` (koperta RAGFlow: `data.chats`). */
async function chatNames(response: Response): Promise<string[]> {
  const body = (await response.json()) as { data?: { chats?: { name?: string }[] } }
  return (body.data?.chats ?? []).map((chat) => chat.name ?? '')
}

test('S6-10: admin zakłada użytkownika i udostępnia mu jeden z dwóch czatów', async ({
  page,
  request,
  browser,
}) => {
  const email = `s10-${Date.now()}@wd.test`

  // a. Dane scenariusza przez API konta admina; lista czatów startuje pusta (reset K9 w global-setup).
  const token = await apiLogin(request)
  await deleteAllChats(request, token)
  const chatAId = await createChat(request, token, { name: CHAT_A })
  await createChat(request, token, { name: CHAT_B })
  // Konto powstaje w kroku c — sprzątanie usuwa je tylko wtedy, gdy faktycznie je założono
  // (przy wcześniejszej awarii `deleteUserByEmail` rzuciłby „brak konta" i zamaskował przyczynę).
  let userCreated = false

  try {
    // b. Admin przez UI: menu boczne → „Administracja" → zakładka Użytkownicy.
    await loginViaUi(page)
    await page.getByRole('navigation').getByRole('link', { name: 'Administracja' }).click()
    await expect(page).toHaveURL(/\/admin\/users$/)
    await expect(page.getByTestId('admin-users')).toBeVisible()

    // c. Nowe konto; po zamknięciu dialogu wiersz pojawia się w siatce.
    await createUserViaUi(page, { email, password: USER_PASSWORD, nickname: 'S10 użytkownik' })
    await expect(page.getByTestId('admin-users')).toContainText(email)
    userCreated = true

    // Jasny motyw, główny ekran scenariusza: siatka użytkowników po dodaniu konta.
    await expectNoSeriousA11y(page, 'S6-10 admin użytkownicy')

    // c2. Klucz API z datą wygaśnięcia (K14 §3): tworzymy go w dialogu kluczy, a po przeładowaniu
    // strony i ponownym otwarciu dialogu kolumna „Wygasa" pokazuje datę, nie „Bezterminowy".
    const expiresAt = tomorrowLocal()
    const keyDialog = await openUserKeysDialog(page, email)
    await keyDialog.getByLabel('Nazwa klucza').fill(KEY_NAME)
    // `data-testid` siedzi na `FormControl` (MUI `TextField`), więc pole to jego `input`.
    await keyDialog.getByTestId('admin-key-expires').locator('input').fill(expiresAt)
    await keyDialog.getByRole('button', { name: 'Utwórz klucz' }).click()
    await expect(keyDialog.getByTestId('admin-key-token')).toBeVisible()
    await keyDialog.getByRole('button', { name: 'Zamknij' }).click()
    await expect(keyDialog).toBeHidden()

    await page.reload()
    const keysAfterReload = await openUserKeysDialog(page, email)
    // Kolumny wiersza: nazwa, prefiks, utworzono, ostatnio użyty, Wygasa, akcje.
    const expiresCell = keysAfterReload
      .getByRole('row')
      .filter({ hasText: KEY_NAME })
      .locator('td')
      .nth(4)
    await expect(expiresCell).not.toHaveText('Bezterminowy')
    await expect(expiresCell).toContainText(String(new Date(expiresAt).getFullYear()))
    await keysAfterReload.getByRole('button', { name: 'Zamknij' }).click()

    // d. Zakładka „Dostęp do asystentów": grant tylko na czat A.
    await page.getByTestId('admin-tab-access').click()
    await expect(page.getByTestId('admin-access')).toBeVisible()
    await grantAccessViaUi(page, email, [chatAId])

    // Tryb ciemny (§C5): przełączamy motyw selektorem w nagłówku, sprawdzamy zakładkę dostępu
    // i wracamy do jasnego, żeby dalsze kroki (drugi kontekst) widziały domyślny stan.
    await page.getByRole('button', { name: 'Tryb kolorów' }).click()
    await page.getByRole('menuitem', { name: 'Ciemny' }).click()
    await expect(page.locator('html')).toHaveAttribute('data-mui-color-scheme', 'dark')
    await expectNoSeriousA11y(page, 'S6-10 admin dostęp do asystentów (ciemny)')
    await page.getByRole('button', { name: 'Tryb kolorów' }).click()
    await page.getByRole('menuitem', { name: 'Jasny' }).click()
    await expect(page.locator('html')).toHaveAttribute('data-mui-color-scheme', 'light')

    // e. Drugi kontekst przeglądarki — nowy użytkownik bez uprawnień administratora.
    const context = await browser.newContext({
      locale: 'pl-PL',
      // Fixture `browser` to surowa przeglądarka (opcje z konfiguracji nie są dziedziczone przez
      // `newContext`), więc adres stosu podajemy jawnie z `WD_E2E_BASE_URL` ustawianego w `run.sh`.
      baseURL: process.env.WD_E2E_BASE_URL,
    })
    try {
      const userPage = await context.newPage()
      const consoleErrors = watchConsoleErrors(userPage)

      await loginViaUiAs(userPage, email, USER_PASSWORD)
      const nav = userPage.getByRole('navigation')
      await expect(nav.getByRole('link', { name: 'Administracja' })).toHaveCount(0)

      const listResponse = userPage.waitForResponse(
        (response) =>
          response.request().method() === 'GET' &&
          new URL(response.url()).pathname === '/api/v1/chats',
      )
      await nav.getByRole('link', { name: 'Czat' }).click()
      await expect(userPage).toHaveURL(/\/chats$/)
      await expect(userPage.getByTestId('chat-card').filter({ hasText: CHAT_A })).toBeVisible()

      // Dowód do komunikatu asercji: dokładna odpowiedź `GET /api/v1/chats` widziana przez użytkownika.
      const listed = await listResponse
      expect(listed.status(), `GET /api/v1/chats → HTTP ${listed.status()}`).toBe(200)
      const names = await chatNames(listed)
      const evidence = `GET /api/v1/chats → HTTP ${listed.status()}, czaty: [${names.join(', ')}]`
      expect(names, `grant na „${CHAT_A}" musi dawać go na liście; ${evidence}`).toContain(CHAT_A)
      expect(names, `brak grantu: „${CHAT_B}" nie może być na liście; ${evidence}`).not.toContain(
        CHAT_B,
      )
      await expect(userPage.getByTestId('chat-card').filter({ hasText: CHAT_B })).toHaveCount(0)

      // f. Tryb ciemny i język EN — ustawienie i przetrwanie przeładowania.
      await userPage.getByRole('button', { name: 'Tryb kolorów' }).click()
      await userPage.getByRole('menuitem', { name: 'Ciemny' }).click()
      await userPage.getByRole('button', { name: 'Język' }).click()
      await userPage.getByRole('menuitem', { name: 'English' }).click()
      await expect(nav.getByRole('link', { name: 'Chat' })).toBeVisible()

      await userPage.reload()
      await expect(userPage.locator('html')).toHaveAttribute('data-mui-color-scheme', 'dark')
      await expect(
        userPage.getByRole('navigation').getByRole('link', { name: 'Chat' }),
      ).toBeVisible()

      expect(consoleErrors, 'błędy konsoli/pageerror w drugim kontekście').toEqual([])
    } finally {
      await context.close()
    }
  } finally {
    // g. Sprzątanie: czaty tenantu i konto użytkownika (kaskadowo, razem z jego zasobami).
    await deleteAllChats(request, token)
    if (userCreated) await deleteUserByEmail(request, token, email)
  }
})
