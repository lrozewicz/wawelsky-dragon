// SC-V12-07 (work/wp/V12/SCENARIOS.md): „Nie tracę zmian przez Esc” — szuflady ustawień czatu,
// ustawień wyszukiwarki i metadanych pliku przy zamknięciu z niezapisanymi zmianami (Esc, klik
// w tło, „Anuluj”, ✕) pytają „Odrzucić zmiany?” [„Wróć do edycji” / „Odrzuć”], a przy czystym
// formularzu zamykają się od razu, bez dialogu. Testy pisane PRZED poprawką (czerwone z
// właściwej przyczyny: dialog nie istnieje dla czatu i metadanych; search ma własny wariant
// z inną treścią). Wzorzec struktury: s27-e67z2-f.spec.ts (uiSession, expectNoLayoutDefects).
import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const SHOTS = process.env.WD_SHOTS_DIR ?? ''

const session = uiSession('s28-v12-discard')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(240_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

let corpus: SeededCorpus
let chatId = ''
let searchId = ''
let token = ''
const docName = 'e2e-v12-discard-metadane.txt'
test.beforeAll(async ({ request }) => {
  token = await apiLogin(request)
  corpus = await seedCorpus(request, token, {
    datasetName: `E2E V12-07 ${Date.now()}`,
    documentName: docName,
    documentBody: 'Sprawozdanie na potrzeby scenariusza odrzucania zmian w szufladach.',
  })
  chatId = await createChat(request, token, { name: `E2E V12-07 czat ${Date.now()}` })
  const created = await request.post(`${API_URL}/api/v1/searches`, {
    headers: { authorization: `Bearer ${token}` },
    data: { name: `E2E V12-07 wyszukiwarka ${Date.now()}` },
  })
  const body = (await created.json()) as { code: number; data: { search_id: string } }
  expect(body.code, 'POST /api/v1/searches').toBe(0)
  searchId = body.data.search_id
})
test.afterAll(async ({ request }) => {
  await deleteDataset(request, token, corpus.datasetId)
  await request.delete(`${API_URL}/api/v1/chats`, {
    headers: { authorization: `Bearer ${token}` },
    data: { ids: [chatId] },
  })
  await request.delete(`${API_URL}/api/v1/searches/${searchId}`, {
    headers: { authorization: `Bearer ${token}` },
  })
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Szuflada ustawień czatu — po treści nagłówka (paper nie ma `aria-label`). */
function chatDrawer(page: Page): Locator {
  return page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia czatu' })
}

/** Szuflada ustawień wyszukiwarki — po treści nagłówka. */
function searchDrawer(page: Page): Locator {
  return page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia wyszukiwarki' })
}

const DISCARD = 'Odrzucić zmiany?'
const KEEP = 'Wróć do edycji'
const DISCARD_BUTTON = 'Odrzuć'

/** Dialog „Odrzucić zmiany?” — po nazwie, bo otwarta szuflada też ma `role="dialog"`. */
function discardDialog(page: Page): Locator {
  return page.getByRole('dialog', { name: DISCARD })
}

/**
 * Zmiana temperatury w zakładce „Model” (preset „Własne” odblokowuje suwaki): `fill()` na
 * natywnym `<input type="range">` (klik przechwytuje kciuk MUI Slider — „intercepts pointer
 * events”). Zwraca wartość po zmianie (0,5; stan początkowy presetu „Precyzja” to 0,2).
 */
async function changeTemperature(page: Page): Promise<string> {
  await page.getByRole('tab', { name: 'Model' }).click()
  await page.getByRole('combobox', { name: 'Kreatywność' }).click()
  await page.getByRole('option', { name: 'Własne' }).click()
  await page.getByRole('button', { name: 'Zaawansowane' }).click()
  const slider = page.getByRole('slider', { name: 'Temperatura' })
  await expect(slider).toBeEnabled()
  await slider.fill('0.5')
  const value = await slider.getAttribute('aria-valuenow')
  expect(value, 'suwak temperatury ma wartość po zmianie').not.toBeNull()
  return value as string
}

/** Koniec animacji wejścia szuflady (slajd MUI) przed pomiarem/zrzutem (wzór: s22). */
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
 * Koniec animacji WYJŚCIA szuflady: `toBeHidden` zapala się w trakcie slajdu, a strażnik układu
 * mierzy ekran już po teście — w pozie pośredniej widzi paper poza oknem (`off-screen`, bieg
 * 2026-10-16: szuflada Search [1174,0]). Czekamy na odmontowanie paperu; `boundingBox()` odpada,
 * bo na lokatorze bez dopasowania auto-czeka do timeoutu zamiast zwrócić null (sonda DOM,
 * zzz-probe: po `toBeHidden` settings-drawer znika z `.MuiDrawer-paper` od razu).
 */
async function drawerGone(drawer: Locator): Promise<void> {
  await expect.poll(async () => await drawer.count()).toBe(0)
}

test('SC-V12-07 czat: zmiana → Esc → „Odrzucić zmiany?”; Esc w dialogu wraca do edycji', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await expect(chatDrawer(page)).toBeVisible()
  const changed = await changeTemperature(page)

  await page.keyboard.press('Escape')
  const dialog = discardDialog(page)
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: KEEP })).toBeVisible()
  await expect(dialog.getByRole('button', { name: DISCARD_BUTTON })).toBeVisible()

  // Esc w dialogu = „Wróć do edycji”: dialog znika, szuflada zostaje, zmiana zachowana.
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(chatDrawer(page)).toBeVisible()
  await expect(page.getByRole('slider', { name: 'Temperatura' })).toHaveAttribute(
    'aria-valuenow',
    changed,
  )

  // Ponowne Esc przy nadal niezapisanej zmianie znów pyta.
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
})

test('SC-V12-07 czat: „Odrzuć” zamyka szufladę, ponowne otwarcie pokazuje stare wartości', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await changeTemperature(page)
  await page.keyboard.press('Escape')
  await expect(discardDialog(page)).toBeVisible()

  await discardDialog(page).getByRole('button', { name: DISCARD_BUTTON }).click()
  await expect(discardDialog(page)).toBeHidden()
  await expect(chatDrawer(page)).toBeHidden()

  // Stara wartość: preset „Precyzja” (temperatura 0,2), suwak znowu zablokowany.
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await expect(chatDrawer(page)).toBeVisible()
  await page.getByRole('tab', { name: 'Model' }).click()
  await expect(page.getByRole('combobox', { name: 'Kreatywność' })).toHaveValue('Precyzja')
  await page.getByRole('button', { name: 'Zaawansowane' }).click()
  const slider = page.getByRole('slider', { name: 'Temperatura' })
  await expect(slider).toBeDisabled()
  await expect(slider).toHaveAttribute('aria-valuenow', '0.2')
})

test('SC-V12-07 czat: bez zmian Esc/„Anuluj”/tło zamykają szufladę od razu, bez dialogu', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/chat/${chatId}`)

  // Esc bez zmian.
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await expect(chatDrawer(page)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(chatDrawer(page)).toBeHidden()
  await expect(discardDialog(page)).toBeHidden()

  // „Anuluj” bez zmian.
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await expect(chatDrawer(page)).toBeVisible()
  await page.getByRole('button', { name: 'Anuluj' }).click()
  await expect(chatDrawer(page)).toBeHidden()
  await expect(discardDialog(page)).toBeHidden()

  // Klik w tło (backdrop) bez zmian.
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await drawerSettled(page, chatDrawer(page))
  await page.mouse.click(100, 400)
  await expect(chatDrawer(page)).toBeHidden()
  await expect(discardDialog(page)).toBeHidden()
  await drawerGone(chatDrawer(page))
})

test('SC-V12-07 czat: przy zmianie tło/„Anuluj”/✕ → dialog „Odrzucić zmiany?”', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await expect(chatDrawer(page)).toBeVisible()
  await page.getByRole('tab', { name: 'Model' }).click()
  await page.getByRole('combobox', { name: 'Kreatywność' }).click()
  await page.getByRole('option', { name: 'Własne' }).click()

  // Klik w tło przy zmianie → dialog; „Wróć do edycji” zostawia szufladę otwartą.
  await drawerSettled(page, chatDrawer(page))
  await page.mouse.click(100, 400)
  await expect(discardDialog(page)).toBeVisible()
  await discardDialog(page).getByRole('button', { name: KEEP }).click()
  await expect(discardDialog(page)).toBeHidden()
  await expect(chatDrawer(page)).toBeVisible()

  // „Anuluj” przy zmianie → dialog.
  await page.getByRole('button', { name: 'Anuluj' }).click()
  await expect(discardDialog(page)).toBeVisible()
  await discardDialog(page).getByRole('button', { name: KEEP }).click()

  // ✕ w nagłówku przy zmianie → dialog; „Odrzuć” zamyka szufladę.
  await page.getByRole('button', { name: 'Zamknij' }).click()
  await expect(discardDialog(page)).toBeVisible()
  await discardDialog(page).getByRole('button', { name: DISCARD_BUTTON }).click()
  await expect(chatDrawer(page)).toBeHidden()
  await drawerGone(chatDrawer(page))
})

test('SC-V12-07 search: zmiana → Esc → dialog → „Odrzuć”; bez zmian „Anuluj” zamyka od razu', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  // Świeża wyszukiwarka bez baz otwiera szufladę ustawień sama (kontrakt §4, jak S6-12 krok 3)
  // — gear pod spodem jest zasłonięty, pierwsze otwarcie bierze z auto-otwarcia.
  await page.goto(`/search/${searchId}`)
  await expect(searchDrawer(page)).toBeVisible()

  // Bez zmian: „Anuluj” zamyka od razu, bez dialogu.
  await searchDrawer(page).getByRole('button', { name: 'Anuluj' }).click()
  await expect(searchDrawer(page)).toBeHidden()
  await expect(discardDialog(page)).toBeHidden()

  // Zmiana nazwy → Esc → dialog z treścią dla kontekstu wyszukiwarki → „Odrzuć”.
  await page.getByRole('button', { name: 'Otwórz ustawienia wyszukiwarki' }).click()
  await expect(searchDrawer(page)).toBeVisible()
  const name = searchDrawer(page).getByLabel('Nazwa wyszukiwarki')
  const original = await name.inputValue()
  await name.fill(`${original} zmieniona`)
  await page.keyboard.press('Escape')
  const dialog = discardDialog(page)
  await expect(dialog).toBeVisible()
  await expect(
    dialog.getByText('Niezapisane zmiany w ustawieniach wyszukiwarki zostaną utracone.'),
  ).toBeVisible()
  await dialog.getByRole('button', { name: DISCARD_BUTTON }).click()
  await expect(searchDrawer(page)).toBeHidden()

  // Ponowne otwarcie: stara nazwa. Na koniec zamknięcie bez zmian (trzecia ścieżka) i koniec
  // animacji wyjścia — strażnik układu mierzy ekran już po teście (off-screen w połowie slajdu).
  await page.getByRole('button', { name: 'Otwórz ustawienia wyszukiwarki' }).click()
  await expect(searchDrawer(page).getByLabel('Nazwa wyszukiwarki')).toHaveValue(original)
  await searchDrawer(page).getByRole('button', { name: 'Anuluj' }).click()
  await expect(searchDrawer(page)).toBeHidden()
  await drawerGone(searchDrawer(page))
})

test('SC-V12-07 metadane: zmiana → Esc → dialog → „Odrzuć”; bez zmian „Anuluj” zamyka od razu', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/files/${corpus.datasetId}`)
  const row = page.getByRole('row', { name: new RegExp(docName) })
  await expect(row).toBeVisible()
  const drawer = page.getByRole('dialog', { name: docName })

  // Bez zmian: „Anuluj” zamyka od razu, bez dialogu.
  await row.getByTestId('row-actions-menu').click()
  await page.getByTestId('row-action-metadata').click()
  await expect(drawer).toBeVisible()
  await drawer.getByRole('button', { name: 'Anuluj' }).click()
  await expect(drawer).toBeHidden()
  await expect(discardDialog(page)).toBeHidden()

  // Zmiana (nowe pole) → Esc → dialog → „Odrzuć”.
  await row.getByTestId('row-actions-menu').click()
  await page.getByTestId('row-action-metadata').click()
  await expect(drawer).toBeVisible()
  await drawer.getByRole('button', { name: '+ Pole' }).click()
  await drawer.getByLabel('Klucz').fill('typ')
  await drawer.getByLabel('Wartość').fill('raport')
  await page.keyboard.press('Escape')
  const dialog = discardDialog(page)
  await expect(dialog).toBeVisible()
  await expect(
    dialog.getByText('Niezapisane zmiany w metadanych pliku zostaną utracone.'),
  ).toBeVisible()
  await dialog.getByRole('button', { name: DISCARD_BUTTON }).click()
  await expect(drawer).toBeHidden()

  // Ponowne otwarcie: stan początkowy (puste metadane).
  await row.getByTestId('row-actions-menu').click()
  await page.getByTestId('row-action-metadata').click()
  await expect(drawer).toBeVisible()
  await expect(drawer.getByText('Brak metadanych — dodaj pierwsze pole')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await drawerGone(drawer)
})

test('SC-V12-07 zrzuty dialogu 1280/390, jasny i ciemny', async ({ page }) => {
  for (const [name, width, height, dark] of [
    ['1280-jasny', 1280, 800, false],
    ['1280-ciemny', 1280, 800, true],
    ['390-jasny', 390, 844, false],
    ['390-ciemny', 390, 844, true],
  ] as const) {
    await page.emulateMedia({ colorScheme: dark ? 'dark' : 'light' })
    await page.setViewportSize({ width, height })
    await page.goto(`/chat/${chatId}`)
    await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
    await expect(chatDrawer(page)).toBeVisible()
    await changeTemperature(page)
    await page.keyboard.press('Escape')
    const dialog = discardDialog(page)
    await expect(dialog).toBeVisible()
    // Koniec animacji Fade dialogu przed zrzutem (wzór: s07 — axe/ocena na stanie docelowym).
    await expect(page.locator('.MuiDialog-container')).toHaveCSS('opacity', '1')
    await drawerSettled(page, chatDrawer(page))
    await page.waitForTimeout(100)
    await shot(page, `sc-v12-07-dialog-${name}`)
    await expectNoLayoutDefects(page, `SC-V12-07 dialog odrzucania (${name})`)
    // Sprzątanie stanu przed kolejnym wariantem: „Odrzuć” zamyka dialog i szufladę.
    await dialog.getByRole('button', { name: DISCARD_BUTTON }).click()
    await expect(chatDrawer(page)).toBeHidden()
    await drawerGone(chatDrawer(page))
  }
})

test('SC-V12-07 EN: „Discard changes?” z „Keep editing”/„Discard”', async ({ page, request }) => {
  await setProfileLanguage(request, token, 'en')
  try {
    await page.setViewportSize({ width: 1280, height: 800 })
    await page.goto(`/chat/${chatId}`)
    await page.getByRole('button', { name: 'Chat settings' }).click()
    await page.getByRole('tab', { name: 'Model' }).click()
    await page.getByRole('combobox', { name: 'Creativity' }).click()
    await page.getByRole('option', { name: 'Custom' }).click()
    await page.keyboard.press('Escape')
    const dialog = page.getByRole('dialog', { name: 'Discard changes?' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Keep editing' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Discard' })).toBeVisible()
    await expect(dialog.getByText('Unsaved changes in chat settings will be lost.')).toBeVisible()
    await dialog.getByRole('button', { name: 'Keep editing' }).click()
    await expect(dialog).toBeHidden()
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})
