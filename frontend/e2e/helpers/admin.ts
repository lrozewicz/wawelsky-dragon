// Pomocniki scenariusza S6-10 (brief WP E3-6c2/T7): zakładanie konta i nadawanie dostępu do
// czatów przez UI oraz sprzątanie konta przez API administracyjne. `ok` nie jest eksportowane
// z `../helpers`, więc mamy tu jego kopię — w wariancie dla tras wd (kontrakt §0: sukces to
// `{data}` albo 204 bez ciała, bez pola `code` znanego z koperty RAGFlow).
import { expect } from '@playwright/test'
import type {
  APIRequestContext,
  APIResponse,
  ConsoleMessage,
  Locator,
  Page,
} from '@playwright/test'

const API_URL = process.env.WD_E2E_API_URL ?? ''

type WdEnvelope<T> = { data: T }
type WdUserRow = { id: string; email: string }

/** Nowe konto zakładane przez UI — pola dialogu „Nowy użytkownik”. */
export type NewUser = { email: string; password: string; nickname: string }

/**
 * Sprawdza status odpowiedzi trasy wd i rozwija jej kopertę. Ciało czytamy raz (`text()`),
 * bo komunikat błędu nie może zużyć strumienia przed `JSON.parse`; 204 ciała nie ma.
 */
async function ok<T>(
  pending: Promise<APIResponse>,
  label: string,
  expectedStatus = 200,
): Promise<T> {
  const response = await pending
  const text = await response.text()
  expect(response.status(), `${label}: HTTP ${response.status()} — ${text}`).toBe(expectedStatus)
  if (expectedStatus === 204) return undefined as unknown as T
  return (JSON.parse(text) as WdEnvelope<T>).data
}

// 401 z `/api/v1/auth/refresh` to oczekiwany stan „brak sesji" (08 §5.3) — ten sam filtr,
// co w strażniku fixture `page` (`../fixtures.ts`).
function isExpectedRefresh401(message: ConsoleMessage): boolean {
  return message.text().includes('401') && message.location().url.includes('/api/v1/auth/refresh')
}

/**
 * Strażnik błędów konsoli dla kontekstu przeglądarki utworzonego ręcznie (drugi kontekst
 * scenariusza nie dostaje fixture `page`). Zwraca żywą tablicę — scenariusz asertuje ją na końcu.
 */
export function watchConsoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && !isExpectedRefresh401(message)) {
      errors.push(`${message.text()} (${message.location().url})`)
    }
  })
  page.on('pageerror', (error) => {
    errors.push(`pageerror: ${error.message}`)
  })
  return errors
}

/** Logowanie dowolnym kontem przez UI (wzór: `loginViaUi` dla admina w `../helpers`). */
export async function loginViaUiAs(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/')
  await page.getByTestId('login-email').fill(email)
  await page.getByTestId('login-password').fill(password)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('home-banner')).toBeVisible()
}

/** Zakłada konto w zakładce „Użytkownicy”; sukces zamyka dialog (kontrakt §4). */
export async function createUserViaUi(page: Page, user: NewUser): Promise<void> {
  await page.getByTestId('admin-users-new').click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('E-mail').fill(user.email)
  await dialog.getByLabel('Hasło początkowe').fill(user.password)
  await dialog.getByLabel('Nazwa').fill(user.nickname)
  await dialog.getByTestId('admin-create-user-submit').click()
  await expect(dialog).toBeHidden()
}

/**
 * Nadaje dostęp w zakładce „Dostęp do asystentów”: wybór e-maila (`Autocomplete` freeSolo,
 * zatwierdzenie Enterem) i zapis zbioru grantów. Czekamy na odpowiedź z grantami, zanim
 * zaznaczymy czaty — inaczej świeżo pobrana lista cofnęłaby lokalny wybór (`AccessPage`).
 */
export async function grantAccessViaUi(
  page: Page,
  email: string,
  chatIds: readonly string[],
): Promise<void> {
  const emailInput = page.getByTestId('admin-access-email')
  const grantsLoaded = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      new URL(response.url()).pathname === '/api/wd/v1/access/assistants',
  )
  await emailInput.fill(email)
  await emailInput.press('Enter')
  await grantsLoaded
  for (const chatId of chatIds) {
    await page.getByTestId(`admin-access-chat-${chatId}`).check()
  }
  await page.getByTestId('admin-access-save').click()
  await expect(page.getByText('Dostęp zapisany.')).toBeVisible()
}

/**
 * Otwiera dialog „Klucze API" wiersza użytkownika o podanym e-mailu (kontrakt WP E3-H2b §C5).
 * Wiersz siatki znajdujemy po e-mailu, akcję po `aria-label` przycisku menu (`UserActionsMenu`).
 */
export async function openUserKeysDialog(page: Page, email: string): Promise<Locator> {
  const row = page.getByRole('row').filter({ hasText: email })
  await row.getByRole('button', { name: 'Akcje użytkownika' }).click()
  await page.getByRole('menuitem', { name: 'Klucze API' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  return dialog
}

/** Usuwa konto po e-mailu (GET z filtrem `email`, potem DELETE z `mode=cascade`). */
export async function deleteUserByEmail(
  request: APIRequestContext,
  token: string,
  email: string,
): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  const found = await ok<{ items: WdUserRow[] }>(
    request.get(`${API_URL}/api/wd/v1/users?email=${encodeURIComponent(email)}`, { headers }),
    'GET /api/wd/v1/users?email',
  )
  const user = found.items.find((item) => item.email === email)
  if (user === undefined) {
    throw new Error(`GET /api/wd/v1/users?email=${email}: brak konta w odpowiedzi`)
  }
  await ok<undefined>(
    request.delete(`${API_URL}/api/wd/v1/users/${user.id}?mode=cascade`, { headers }),
    `DELETE /api/wd/v1/users/${user.id}?mode=cascade`,
    204,
  )
}
