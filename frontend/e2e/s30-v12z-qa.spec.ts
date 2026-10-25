// Poprawki MAJOR z QA-UI V12-z (work/qa/V12-z-2/WYNIKI-QA.md, brief T1):
// - SC-V12-08 (Search, D2): niepoprawny formularz szuflady wyszukiwarki (brak bazy) → „Zapisz”
//   NIEAKTYWNY z powodem „Popraw: …” pod przyciskiem i `aria-describedby` (jak w datasetach
//   i „Dodaj model” — dotąd klik był cichym no-opem).
// - SC-V12-z-D3: użytkownik z udostępnionym czatem (bez grantu na bazę) widzi czytelną etykietę
//   „Baza niedostępna (…xxxxxx)” zamiast surowego UUID bazy — chip i pozycja na liście.
// - SC-V12-z-D1: dymek suwaka pokazuje wartość zaokrągloną do 2 miejsc, nigdy
//   „0.44999999999999996” (strzałki MUI dodają krok wprost).
// Wzorce: s28-v12-hints.spec.ts (powód Zapisz), s10-admin-access.spec.ts (konto + grant +
// drugi kontekst), s28-v12-discard.spec.ts (suwaki temperatury w zakładce „Model”).
import type { APIRequestContext, Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, createDataset, seedCorpus } from './helpers'
import {
  createUserViaUi,
  deleteUserByEmail,
  grantAccessViaUi,
  loginViaUiAs,
  watchConsoleErrors,
} from './helpers/admin'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

const SHOTS = process.env.WD_SHOTS_DIR ?? ''

const session = uiSession('s30-v12z-qa')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(180_000)

/** Unikalny sufiks nazw zasobów (wzór s28). */
function uniq(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`
}

/** Współdzielony token admina na cały bieg pliku (limiter logowań — wzór s28). */
let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

/** Hasło konta użytkownika z seedu scenariusza D3 (jak w s10). */
const USER_PASSWORD = 'wd-test-user-1'

/** Zasoby do sprzątania po biegu (wzór s28/s10). */
const createdSearches: string[] = []
const createdDatasets: string[] = []
const createdChats: string[] = []
let createdUserEmail = ''

test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

test.afterEach(async ({ context }) => {
  await session.save(context)
})

test.afterAll(async ({ request }) => {
  const token = await adminToken(request)
  const headers = { authorization: `Bearer ${token}` }
  for (const id of createdSearches.splice(0)) {
    await request.delete(`${process.env.WD_E2E_API_URL}/api/v1/searches/${id}`, { headers })
  }
  for (const id of createdChats.splice(0)) {
    await request.delete(`${process.env.WD_E2E_API_URL}/api/v1/chats`, {
      headers,
      data: { ids: [id] },
    })
  }
  for (const id of createdDatasets.splice(0)) {
    await request.delete(`${process.env.WD_E2E_API_URL}/api/v1/datasets/${id}`, { headers })
  }
  if (createdUserEmail !== '') await deleteUserByEmail(request, token, createdUserEmail)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/**
 * Koniec animacji wejścia szuflady (slajd MUI) przed pomiarem/zrzutem — strażnik układu w pozie
 * pośredniej widzi paper poza oknem (wzór: s28-v12-discard).
 */
async function drawerSettled(page: Page, drawer: Locator): Promise<void> {
  const viewportWidth = page.viewportSize()?.width ?? 0
  await expect
    .poll(async () => {
      const box = await drawer.boundingBox()
      return box === null ? Number.POSITIVE_INFINITY : box.x + box.width
    })
    .toBeLessThanOrEqual(viewportWidth)
}

/**
 * Powód nieaktywnego przycisku (SC-V12-08 k1): `aria-describedby` prowadzi do widocznego
 * elementu z dokładnie tym tekstem (wzór s28-v12-hints).
 */
async function expectDisabledReason(save: Locator, reason: string): Promise<void> {
  await expect(save).toBeDisabled()
  await expect(save).toHaveAttribute('aria-describedby', /.+/)
  const hintId = await save.getAttribute('aria-describedby')
  await expect(save.page().locator(`#${hintId ?? ''}`)).toHaveText(reason)
}

test('SC-V12-08 (Search): „Zapisz” nieaktywny z powodem „Popraw: Bazy wiedzy” i aria-describedby', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const token = await adminToken(request)
  const datasetName = `E2E S30 baza search ${uniq()}`
  const datasetId = await createDataset(request, token, datasetName)
  createdDatasets.push(datasetId)
  const searchName = `E2E S30 wyszukiwarka ${uniq()}`
  // Wyszukiwarka BEZ baz: szuflada ustawień otwiera się samoczynnie (SearchPage, hasNoKb).
  const searchId = await createSearchViaApi(request, token, searchName)
  createdSearches.push(searchId)

  await page.goto(`/search/${searchId}`)
  const drawer = page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia wyszukiwarki' })
  await expect(drawer).toBeVisible()
  await drawerSettled(page, drawer)

  const save = page.getByRole('button', { name: 'Zapisz' })
  await expectDisabledReason(save, 'Popraw: Bazy wiedzy')
  // Błąd pola zostaje przy polu (pomoc „Wybierz co najmniej jedną bazę wiedzy.”).
  await expect(page.getByText('Wybierz co najmniej jedną bazę wiedzy.')).toBeVisible()
  await expect(page.locator('#search-settings-save-reason')).toBeVisible()
  await shot(page, 's30-search-reason-1280')
  await expectNoLayoutDefects(page, 'szuflada wyszukiwarki z powodem nieaktywnego Zapisz')

  // Wybór bazy: formularz poprawny → przycisk aktywny, powód i atrybut znikają.
  await page.getByRole('combobox', { name: 'Bazy wiedzy' }).click()
  await page.getByRole('option', { name: datasetName }).click()
  await expect(save).toBeEnabled()
  expect(await save.getAttribute('aria-describedby'), 'atrybut powodu zdjęty').toBeNull()
  await expect(page.locator('#search-settings-save-reason')).toHaveCount(0)
})

test.describe('SC-V12-08 (Search) w ciemnym motywie', () => {
  test.use({ colorScheme: 'dark' })

  test('390: powód pod „Zapisz” mieści się w szufladzie (zrzut ciemny)', async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const token = await adminToken(request)
    const searchId = await createSearchViaApi(request, token, `E2E S30 ciemny ${uniq()}`)
    createdSearches.push(searchId)

    await page.goto(`/search/${searchId}`)
    const drawer = page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia wyszukiwarki' })
    await expect(drawer).toBeVisible()
    await drawerSettled(page, drawer)
    const save = page.getByRole('button', { name: 'Zapisz' })
    await expectDisabledReason(save, 'Popraw: Bazy wiedzy')
    await save.scrollIntoViewIfNeeded()
    await page.waitForTimeout(300)
    await shot(page, 's30-search-reason-390-dark')
    await expectNoLayoutDefects(page, 'szuflada wyszukiwarki 390 ciemna z powodem Zapisz')
  })
})

test('SC-V12-z-D1: dymek suwaka temperatury pokazuje wartość zaokrągloną do 2 miejsc', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const token = await adminToken(request)
  const chatId = await createChat(request, token, { name: `E2E S30 suwak ${uniq()}` })
  createdChats.push(chatId)

  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Model' }).click()
  await page.getByRole('combobox', { name: 'Kreatywność' }).click()
  await page.getByRole('option', { name: 'Własne' }).click()
  await page.getByRole('button', { name: 'Zaawansowane' }).click()

  const slider = page.getByRole('slider', { name: 'Temperatura' })
  await expect(slider).toBeEnabled()
  await slider.fill('0.2')
  // Najazd na KORZEŃ suwaka otwiera dymek (`valueLabelDisplay="auto"`); natywny input
  // jest niewidoczny dla kursora (hover wisi), a korzeń przyjmuje najazd i klawiaturę.
  const temperatureSlider = page
    .locator('.MuiSlider-root')
    .filter({ has: page.getByRole('slider', { name: 'Temperatura' }) })
  await temperatureSlider.hover()
  for (let i = 0; i < 5; i += 1) await page.keyboard.press('ArrowRight')

  // 0.2 + 5×0.05 liczone wprost to 0.44999999999999996 (defekt D1) — dymek ma pokazać „0.45”.
  const valueLabel = temperatureSlider.locator('.MuiSlider-valueLabel')
  await expect(valueLabel).toHaveText('0.45')
  await shot(page, 's30-slider-label-1280')
})

test('SC-V12-z-D3: udostępniony czat pokazuje „Baza niedostępna (…xxxxxx)” zamiast UUID', async ({
  page,
  browser,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const token = await adminToken(request)
  // Baza z parsowanym dokumentem (seedCorpus): czat przyjmuje wyłącznie bazy z treścią
  // (walidacja `POST /chats` odrzuca pustą — „doesn't own parsed file”, code 102).
  const corpus = await seedCorpus(request, token, {
    datasetName: `E2E S30 baza czatu ${uniq()}`,
    documentName: 'e2e-s30-baza.txt',
    documentBody: 'Treść bazy wiedzy dla scenariusza D3 — udostępnienie czatu bez grantu na bazę.',
  })
  createdDatasets.push(corpus.datasetId)
  const chatName = `E2E S30 czat ${uniq()}`
  const chatId = await createChat(request, token, {
    name: chatName,
    datasetIds: [corpus.datasetId],
  })
  createdChats.push(chatId)
  const email = `s30-${Date.now()}@wd.test`

  // Admin: konto użytkownika i grant na CZAT (nie na bazę — ta zostaje niedostępna).
  await page.goto('/admin/users')
  await expect(page.getByTestId('admin-users')).toBeVisible()
  await createUserViaUi(page, { email, password: USER_PASSWORD, nickname: 'S30 użytkownik' })
  createdUserEmail = email
  await page.getByTestId('admin-tab-access').click()
  await expect(page.getByTestId('admin-access')).toBeVisible()
  await grantAccessViaUi(page, email, [chatId])

  // Drugi kontekst: użytkownik widzi tylko udostępniony czat i otwiera jego ustawienia.
  const context = await browser.newContext({
    locale: 'pl-PL',
    baseURL: process.env.WD_E2E_BASE_URL,
  })
  try {
    const userPage = await context.newPage()
    const consoleErrors = watchConsoleErrors(userPage)
    await userPage.setViewportSize({ width: 1280, height: 800 })
    await loginViaUiAs(userPage, email, USER_PASSWORD)

    await userPage.goto(`/chat/${chatId}`)
    await userPage.getByRole('button', { name: 'Ustawienia czatu' }).click()
    const drawer = userPage.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia czatu' })
    await expect(drawer).toBeVisible()
    await drawerSettled(userPage, drawer)

    // Chip i opcja listy z czytelną etykietą; surowy UUID nie występuje w szufladzie.
    const label = `Baza niedostępna (…${corpus.datasetId.slice(-6)})`
    await expect(userPage.getByText(label)).toBeVisible()
    await shot(userPage, 's30-shared-chat-kb-1280')
    await expectNoLayoutDefects(userPage, 'ustawienia udostępnionego czatu z etykietą bazy')

    await userPage.getByRole('combobox', { name: 'Bazy wiedzy' }).click()
    await expect(userPage.getByRole('option', { name: label })).toBeVisible()
    expect(await drawer.innerText(), 'surowy UUID poza etykietą').not.toContain(corpus.datasetId)
    await userPage.keyboard.press('Escape')

    expect(consoleErrors, 'błędy konsoli/pageerror w drugim kontekście').toEqual([])
  } finally {
    await context.close()
  }
})

/** Wyszukiwarka przez API (wzór `createSearch` z e2e/helpers/searches.ts, bez baz wiedzy). */
async function createSearchViaApi(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<string> {
  const created = await request.post(`${process.env.WD_E2E_API_URL}/api/v1/searches`, {
    headers: { authorization: `Bearer ${token}` },
    data: { name },
  })
  const body = (await created.json()) as { code: number; data: { search_id: string } }
  expect(body.code, 'POST /api/v1/searches').toBe(0)
  return body.data.search_id
}
