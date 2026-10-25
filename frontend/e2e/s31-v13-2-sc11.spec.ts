// SC-V13-11 (work/wp/V13/SCENARIOS.md): szuflada ustawień bez zmian — „Zapisz” nieaktywny
// z widocznym powodem „Brak zmian do zapisania” (EN „No changes to save”), powiązanym
// `aria-describedby`; zmiana pola gasi powód i aktywuje „Zapisz”, cofnięcie przywraca stan
// wyjściowy. Ten sam wzorzec we wszystkich szufladach/podglądach ustawień (CONTRACT V13-2 §3):
// czat, wyszukiwarka, metadane pliku, konfiguracja bazy. Warianty: 390 px (powód nie wypycha
// przycisku poza ekran), EN, ciemny. Testy pisane PRZED poprawką (V13-2 T3) — czerwone
// z właściwej przyczyny: powód nie istniał (czat, metadane), a nieaktywny „Zapisz” stawał
// bez powodu. Wzorce struktury:
// s28-v12-discard.spec.ts (uiSession, szuflady, koniec animacji), U12 w 08-frontend §4.4.
// DEC-372: kolejność powodu to najpierw błąd walidacji (regresja s30-v12z-qa), a „Brak zmian
// do zapisania” dotyczy poprawnego formularza bez zmian — dlatego wyszukiwarka w beforeAll
// powstaje z podpiętą bazą i szufladę otwiera zębatka.
import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { createSearch } from './helpers/searches'
import { uiSession } from './helpers/session'

const SHOTS = process.env.WD_SHOTS_DIR ?? ''
const API_URL = process.env.WD_E2E_API_URL ?? ''
const REASON_PL = 'Brak zmian do zapisania'
const REASON_EN = 'No changes to save'
const SAVE_PL = 'Zapisz'
const SAVE_EN = 'Save'

const session = uiSession('s31-v13-2-sc11')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(240_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

let corpus: SeededCorpus
let chatId = ''
let searchId = ''
let token = ''
const docName = 'e2e-v13-2-sc11-metadane.txt'
const CHAT_NAME = 'E2E V13-2 SC11 czat'

test.beforeAll(async ({ request }) => {
  token = await apiLogin(request)
  corpus = await seedCorpus(request, token, {
    datasetName: `E2E V13-2 SC11 ${Date.now()}`,
    documentName: docName,
    documentBody: 'Sprawozdanie na potrzeby scenariusza powodu nieaktywnego przycisku zapisu.',
  })
  chatId = await createChat(request, token, { name: `${CHAT_NAME} ${Date.now()}` })
  // DEC-372: wyszukiwarka z podpiętą bazą — scenariusz bada stan „bez zmian”, a nie formularz
  // niewalidowany („Popraw: Bazy wiedzy” to osobny przypadek, regresja s30-v12z-qa).
  searchId = await createSearch(request, token, {
    name: `E2E V13-2 SC11 wyszukiwarka ${Date.now()}`,
    datasetIds: [corpus.datasetId],
  })
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
  return chatDrawerByTitle(page, 'Ustawienia czatu')
}

/** Jak wyżej, z tytułem w danym języku (EN: „Chat settings”). */
function chatDrawerByTitle(page: Page, title: string): Locator {
  return page.locator('.MuiDrawer-paper').filter({ hasText: title })
}

/** Szuflada ustawień wyszukiwarki — po treści nagłówka (wzór: s28-v12-discard). */
function searchDrawer(page: Page): Locator {
  return page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia wyszukiwarki' })
}

/** Szuflada metadanych pliku — rola dialog z nazwą dokumentu (wzór: s28-v12-discard). */
function metadataDrawer(page: Page): Locator {
  return page.getByRole('dialog', { name: docName })
}

/** Koniec animacji wejścia szuflady (slajd MUI) przed pomiarem/zrzutem (wzór: s28). */
async function drawerSettled(page: Page, drawer: Locator): Promise<void> {
  const viewportWidth = page.viewportSize()?.width ?? 0
  await expect
    .poll(async () => {
      const box = await drawer.boundingBox()
      return box === null ? Number.POSITIVE_INFINITY : box.x + box.width
    })
    .toBeLessThanOrEqual(viewportWidth)
}

/** Koniec animacji WYJŚCIA szuflady — strażnik układu mierzy ekran już po teście (wzór: s28). */
async function drawerGone(drawer: Locator): Promise<void> {
  await expect.poll(async () => await drawer.count()).toBe(0)
}

/**
 * Nieaktywny „Zapisz” z powodem — k1 (bez zmian) i k3 (po cofnięciu); `phase` tylko
 * podpisuje asercje, żeby czerwony log wskazywał krok scenariusza.
 */
async function expectDisabledWithReason(
  scope: Locator | Page,
  save: Locator,
  phase = 'k1',
): Promise<void> {
  await expect(save, `${phase}: „Zapisz” nieaktywny bez zmian`).toBeDisabled()
  await expect(scope.getByText(REASON_PL), `${phase}: powód widoczny pod przyciskiem`).toBeVisible()
  const describedBy = await save.getAttribute('aria-describedby')
  expect(describedBy, `${phase}: „Zapisz” powiązany z powodem (aria-describedby)`).not.toBeNull()
  await expect(scope.locator(`#${describedBy}`)).toHaveText(REASON_PL)
}

/** K2: po zmianie pola powód znika, „Zapisz” jest aktywny. */
async function expectEnabledWithoutReason(scope: Locator | Page, save: Locator): Promise<void> {
  await expect(save, 'k2: „Zapisz” aktywny po zmianie').toBeEnabled()
  await expect(scope.getByText(REASON_PL), 'k2: powód zniknął').toHaveCount(0)
}

/** K3: cofnięcie do wartości pierwotnej — znowu nieaktywny „Zapisz” z powodem. */
async function afterRevert(scope: Locator | Page, save: Locator): Promise<void> {
  await expectDisabledWithReason(scope, save, 'k3')
}

// ── Szuflada ustawień czatu ────────────────────────────────────────────────────────────────

test('SC-V13-11 czat k1: bez zmian „Zapisz” nieaktywny z powodem', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  const drawer = chatDrawer(page)
  await expect(drawer).toBeVisible()
  await drawerSettled(page, drawer)
  const save = drawer.getByRole('button', { name: SAVE_PL })
  await expectDisabledWithReason(drawer, save)
  await expectNoLayoutDefects(page, 'SC-V13-11 czat k1 — szuflada bez zmian')
})

test('SC-V13-11 czat k2+k3: zmiana aktywuje „Zapisz”, cofnięcie przywraca powód', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  const drawer = chatDrawer(page)
  await expect(drawer).toBeVisible()
  const save = drawer.getByRole('button', { name: SAVE_PL })

  // K2: zmiana pola (preset „Kreatywność” na wartość inną niż bieżąca) → powód znika, aktywny.
  await drawer.getByRole('tab', { name: 'Model' }).click()
  const preset = drawer.getByRole('combobox', { name: 'Kreatywność' })
  const original = await preset.inputValue()
  await preset.click()
  const options = page.getByRole('listbox').getByRole('option')
  const other = (await options.allTextContents())
    .map((name) => name.trim())
    .find((name) => name !== original && name !== '')
  expect(other, 'lista presetów ma wartość inną niż bieżąca').toBeTruthy()
  await page.getByRole('option', { name: other, exact: true }).click()
  await expectEnabledWithoutReason(drawer, save)

  // K3: cofnięcie do wartości pierwotnej → nieaktywny z powodem (jak k1).
  await preset.click()
  await page.getByRole('option', { name: original, exact: true }).click()
  await afterRevert(drawer, save)
  await expectNoLayoutDefects(page, 'SC-V13-11 czat k3 — stan po cofnięciu')
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await drawerGone(drawer)
})

// ── Szuflada ustawień wyszukiwarki ─────────────────────────────────────────────────────────

test('SC-V13-11 wyszukiwarka k1: bez zmian „Zapisz” nieaktywny z powodem', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  // Wyszukiwarka ma bazę (DEC-372), więc szuflada NIE otwiera się sama — otwiera ją zębatka
  // (wzór: s28-v12-discard).
  await page.goto(`/search/${searchId}`)
  await page.getByRole('button', { name: 'Otwórz ustawienia wyszukiwarki' }).click()
  const drawer = searchDrawer(page)
  await expect(drawer).toBeVisible()
  await drawerSettled(page, drawer)
  await expectDisabledWithReason(drawer, drawer.getByRole('button', { name: SAVE_PL }))
  await expectNoLayoutDefects(page, 'SC-V13-11 wyszukiwarka k1 — szuflada bez zmian')
  await drawer.getByRole('button', { name: 'Anuluj' }).click()
  await expect(drawer).toBeHidden()
  await drawerGone(drawer)
})

test('SC-V13-11 wyszukiwarka k2+k3: zmiana aktywuje „Zapisz”, cofnięcie przywraca powód', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/search/${searchId}`)
  await page.getByRole('button', { name: 'Otwórz ustawienia wyszukiwarki' }).click()
  const drawer = searchDrawer(page)
  await expect(drawer).toBeVisible()
  await drawerSettled(page, drawer)
  const save = drawer.getByRole('button', { name: SAVE_PL })
  const name = drawer.getByLabel('Nazwa wyszukiwarki')
  const original = await name.inputValue()

  await name.fill(`${original} zmieniona`)
  await expectEnabledWithoutReason(drawer, save)

  await name.fill(original)
  await afterRevert(drawer, save)
  await expectNoLayoutDefects(page, 'SC-V13-11 wyszukiwarka k3 — stan po cofnięciu')
  await drawer.getByRole('button', { name: 'Anuluj' }).click()
  await expect(drawer).toBeHidden()
  await drawerGone(drawer)
})

// ── Szuflada metadanych pliku ──────────────────────────────────────────────────────────────

async function openMetadataDrawer(page: Page): Promise<Locator> {
  const row = page.getByRole('row', { name: new RegExp(docName) })
  await expect(row).toBeVisible()
  await row.getByTestId('row-actions-menu').click()
  await page.getByTestId('row-action-metadata').click()
  const drawer = metadataDrawer(page)
  await expect(drawer).toBeVisible()
  return drawer
}

test('SC-V13-11 metadane k1: bez zmian „Zapisz” nieaktywny z powodem', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/files/${corpus.datasetId}`)
  const drawer = await openMetadataDrawer(page)
  const save = drawer.getByRole('button', { name: SAVE_PL })
  await expectDisabledWithReason(drawer, save)
  await expectNoLayoutDefects(page, 'SC-V13-11 metadane k1 — szuflada bez zmian')
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await drawerGone(drawer)
})

test('SC-V13-11 metadane k2+k3: zmiana aktywuje „Zapisz”, cofnięcie przywraca powód', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/files/${corpus.datasetId}`)
  const drawer = await openMetadataDrawer(page)
  const save = drawer.getByRole('button', { name: SAVE_PL })

  // K2: nowe pole (klucz + wartość) → powód znika, „Zapisz” aktywny.
  await drawer.getByRole('button', { name: '+ Pole' }).click()
  await drawer.getByLabel('Klucz').fill('typ')
  await drawer.getByLabel('Wartość').fill('raport')
  await expectEnabledWithoutReason(drawer, save)

  // K3: cofnięcie (usunięcie dodanego pola) → nieaktywny z powodem.
  await drawer.getByRole('button', { name: 'Usuń pole' }).click()
  await afterRevert(drawer, save)
  await expectNoLayoutDefects(page, 'SC-V13-11 metadane k3 — stan po cofnięciu')
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await drawerGone(drawer)
})

// ── Konfiguracja bazy (SaveFooter) ──────────────────────────────────────────────────────────

test('SC-V13-11 konfiguracja k1: bez zmian „Zapisz” nieaktywny z powodem', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/configuration/${corpus.datasetId}`)
  const save = page.getByRole('button', { name: SAVE_PL })
  await expectDisabledWithReason(page, save)
  await expectNoLayoutDefects(page, 'SC-V13-11 konfiguracja k1 — formularz bez zmian')
})

test('SC-V13-11 konfiguracja k2+k3: zmiana aktywuje „Zapisz”, cofnięcie przywraca powód', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/configuration/${corpus.datasetId}`)
  const save = page.getByRole('button', { name: SAVE_PL })
  const description = page.getByLabel('Opis')
  const original = await description.inputValue()

  await description.fill(`${original} zmieniona`.trim())
  await expectEnabledWithoutReason(page, save)

  await description.fill(original)
  await afterRevert(page, save)
  await expectNoLayoutDefects(page, 'SC-V13-11 konfiguracja k3 — stan po cofnięciu')
})

// ── Warianty: 390 px, EN, ciemny ────────────────────────────────────────────────────────────

test('SC-V13-11 czat 390 px: powód nie wypycha „Zapisz” poza ekran', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  const drawer = chatDrawer(page)
  await expect(drawer).toBeVisible()
  await drawerSettled(page, drawer)
  const save = drawer.getByRole('button', { name: SAVE_PL })
  await expectDisabledWithReason(drawer, save)

  // Zarówno powód, jak i przycisk mieszczą się w oknie 390×844 — powód nie odpycha stopki.
  const reasonBox = await drawer.getByText(REASON_PL).boundingBox()
  const saveBox = await save.boundingBox()
  expect(reasonBox, 'powód ma wymiar').not.toBeNull()
  expect(saveBox, '„Zapisz” ma wymiar').not.toBeNull()
  expect(reasonBox!.y + reasonBox!.height, 'dół powodu w oknie').toBeLessThanOrEqual(844)
  expect(saveBox!.y + saveBox!.height, 'dół „Zapisz” w oknie').toBeLessThanOrEqual(844)
  expect(saveBox!.y, '„Zapisz” poniżej powodu (widoczny układ)').toBeGreaterThanOrEqual(
    reasonBox!.y,
  )
  await shot(page, 'sc-v13-11-czat-390')
  await expectNoLayoutDefects(page, 'SC-V13-11 czat 390 px — szuflada bez zmian')
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await drawerGone(drawer)
})

test('SC-V13-11 EN: „No changes to save” przy nieaktywnym „Save”', async ({ page, request }) => {
  await setProfileLanguage(request, token, 'en')
  try {
    await page.setViewportSize({ width: 1280, height: 800 })
    await page.goto(`/chat/${chatId}`)
    await page.getByRole('button', { name: 'Chat settings' }).click()
    const drawer = chatDrawerByTitle(page, 'Chat settings')
    await expect(drawer).toBeVisible()
    await drawerSettled(page, drawer)
    const save = drawer.getByRole('button', { name: SAVE_EN })
    await expect(save, 'k1 EN: „Save” nieaktywny bez zmian').toBeDisabled()
    await expect(drawer.getByText(REASON_EN), 'k1 EN: powód widoczny').toBeVisible()
    const describedBy = await save.getAttribute('aria-describedby')
    expect(describedBy, 'k1 EN: powiązanie aria-describedby').not.toBeNull()
    await expect(drawer.locator(`#${describedBy}`)).toHaveText(REASON_EN)
    await expectNoLayoutDefects(page, 'SC-V13-11 EN — szuflada bez zmian')
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})

test('SC-V13-11 ciemny 390 px: powód i „Zapisz” widoczne', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  const drawer = chatDrawer(page)
  await expect(drawer).toBeVisible()
  await drawerSettled(page, drawer)
  const save = drawer.getByRole('button', { name: SAVE_PL })
  await expectDisabledWithReason(drawer, save)
  await shot(page, 'sc-v13-11-czat-390-ciemny')
  await expectNoLayoutDefects(page, 'SC-V13-11 ciemny 390 px — szuflada bez zmian')
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await drawerGone(drawer)
})
