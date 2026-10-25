// SC-V13-12 (work/wp/V13/SCENARIOS.md, U12 w 08-frontend §4.4): dialogi na telefonie (390×844)
// bez pustej przestrzeni — krótkie dialogi (usunięcie czatu/bazy, zmiana nazwy czatu, „Nowy czat”,
// „Nowy klucz API”, „Odrzucić zmiany?”) dopasowane wysokością do treści (wysokość < 70 % okna),
// bez pełnego ekranu (szerokość ≤ okno − 32), marginesy boczne ≥ 16 px, przyciski akcji widoczne.
// Długie (import bazy, eksport bazy, formularz integracji, szczegóły integracji) — pełny ekran
// z nagłówkiem i akcjami zawsze w widoku mimo przewinięcia treści. K3: poziomo 844×390 krótkie
// dialogi mieszczą się albo przewijają treść, akcje widoczne. Testy pisane PRZED poprawką
// (V13-2 T4) — czerwone z właściwej przyczyny. Wzorce struktury: s28-v12-discard.spec.ts
// (uiSession, szuflada czatu), s17-kb-export/s17b-kb-import (menu bazy, „Importuj”), s11
// (integracje na stubie Graph).
import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, createDataset } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { deleteAllIntegrations } from './helpers/integrations'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const SHOTS = process.env.WD_SHOTS_DIR ?? ''

const CHAT_NAME = 'E2E V13-2 SC12 czat'
const DATASET_NAME = 'E2E V13-2 SC12 baza'
const INTEGRATION_NAME = 'E2E V13-2 SC12 integracja'

// Stałe stubu Graph (kontrakt E4-3d C5, wzór: s11-integrations).
const TENANT = 'tenant-e2e'
const CLIENT = 'client-e2e'
const SECRET = 'fake-graph-secret'
const SITE_URL = 'https://contoso.sharepoint.test/sites/e2e'

const session = uiSession('s31-v13-2-sc12')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(240_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

let chatId = ''
let datasetId = ''
let integrationId = 0
let token = ''
// Dopiski T1b (T4): plik do dialogu „Usuń pliki” i czat o długiej nazwie bez spacji (U2).
let fileId = ''
let longNameChatId = ''

const FILE_NAME = 'e2e-sc12-usuniecie-pliku.txt'
// 200 × „x” — najgorszy przypadek zawijania w potwierdzeniu (żadnych spacji/łączników).
const LONG_CHAT_NAME = 'x'.repeat(200)

test.beforeAll(async ({ request }) => {
  token = await apiLogin(request)
  chatId = await createChat(request, token, { name: `${CHAT_NAME} ${Date.now()}` })
  datasetId = await createDataset(request, token, `${DATASET_NAME} ${Date.now()}`)
  longNameChatId = await createChat(request, token, { name: LONG_CHAT_NAME })
  // Plik w menedżerze (root) dla dialogu „Usuń pliki” (odpowiedź: lista utworzonych, §D5).
  const uploaded = await request.post(`${API_URL}/api/v1/files`, {
    headers: { authorization: `Bearer ${token}` },
    multipart: {
      file: {
        name: FILE_NAME,
        mimeType: 'text/plain',
        buffer: Buffer.from('Treść SC-V13-12', 'utf-8'),
      },
    },
  })
  expect(uploaded.status(), 'POST /api/v1/files (plik do dialogu usuwania)').toBe(200)
  const uploadedBody = (await uploaded.json()) as { data: { id: string }[] }
  fileId = uploadedBody.data[0]?.id ?? ''
  expect(fileId, 'odpowiedź uploadu zawiera id pliku').not.toBe('')
  // Integracja dla „szczegółów” (POST jak zapis formularza, kontrakt E4-3d): stub Graph
  // rozwiązuje witrynę, więc tworzenie przechodzi bez klikania po UI.
  await deleteAllIntegrations(request, token)
  const created = await request.post(`${API_URL}/api/wd/v1/integrations`, {
    headers: { authorization: `Bearer ${token}` },
    data: {
      type: 'sharepoint',
      name: INTEGRATION_NAME,
      dataset_id: datasetId,
      tenant_id: TENANT,
      client_id: CLIENT,
      client_secret: SECRET,
      site_url: SITE_URL,
      excluded_library_names: [],
      ignored_extensions: [],
      max_file_size_bytes: 209_715_200,
      scan_interval_seconds: 300,
      delete_propagation: true,
      is_active: false,
    },
  })
  const body = await created.text()
  expect(created.status(), `POST /api/wd/v1/integrations → ${body.slice(0, 200)}`).toBe(201)
  integrationId = (JSON.parse(body) as { data: { id: number } }).data.id
})

test.afterAll(async ({ request }) => {
  await deleteAllIntegrations(request, token)
  await deleteDataset(request, token, datasetId)
  await request.delete(`${API_URL}/api/v1/chats`, {
    headers: { authorization: `Bearer ${token}` },
    data: { ids: [chatId] },
  })
  // Czat o długiej nazwie kasuje się w samym teście (klik „Usuń”); gdy test padł wcześniej —
  // sprzątanie tutaj, plik zawsze tutaj (dialog usuwania tylko otwieramy i zamykamy).
  if (longNameChatId !== '') {
    await request.delete(`${API_URL}/api/v1/chats`, {
      headers: { authorization: `Bearer ${token}` },
      data: { ids: [longNameChatId] },
    })
  }
  if (fileId !== '') {
    await request.delete(`${API_URL}/api/v1/files`, {
      headers: { authorization: `Bearer ${token}` },
      data: { ids: [fileId] },
    })
  }
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Papier otwartego dialogu MUI (Drawer go nie łapie — to inny komponent). */
function paper(page: Page): Locator {
  return page.locator('.MuiDialog-paper')
}

/** Papier w całości w oknie: marginesy boczne ≥ 16 px (U12) — pełny ekran daje margines 0. */
async function expectSideMargins(page: Page, label: string, min: number): Promise<void> {
  const box = (await paper(page).boundingBox()) as { x: number; width: number }
  const vw = page.viewportSize()?.width ?? 0
  expect(box.x, `${label}: lewy margines ≥ ${min} px`).toBeGreaterThanOrEqual(min)
  expect(vw - (box.x + box.width), `${label}: prawy margines ≥ ${min} px`).toBeGreaterThanOrEqual(
    min,
  )
}

/** Koniec animacji wejścia dialogu (Fade MUI) przed pomiarem/zrzutem (wzór: s28). */
async function dialogSettled(page: Page): Promise<void> {
  await expect(page.locator('.MuiDialog-container').first()).toHaveCSS('opacity', '1')
  await page.waitForTimeout(100)
}

/**
 * Krótki dialog (k1): dopasowany wysokością do treści (wysokość < 70 % okna — bez pustej połowy
 * ekranu), bez pełnego ekranu (szerokość ≤ okno − 32), marginesy boczne ≥ 16 px, przyciski akcji
 * widoczne w zasięgu kciuka (w całości w oknie).
 */
async function expectShortDialog(page: Page, label: string, actions: Locator[]): Promise<void> {
  await dialogSettled(page)
  const box = (await paper(page).boundingBox()) as {
    x: number
    y: number
    width: number
    height: number
  }
  const vw = page.viewportSize()?.width ?? 0
  const vh = page.viewportSize()?.height ?? 0
  expect(box, `${label}: dialog widoczny`).not.toBeNull()
  expect(box.height, `${label}: wysokość < 70 % okna (bez pustej przestrzeni)`).toBeLessThan(
    0.7 * vh,
  )
  expect(box.width, `${label}: szerokość ≤ okno − 32 (brak fullScreen)`).toBeLessThanOrEqual(
    vw - 32,
  )
  await expectSideMargins(page, label, 16)
  for (const action of actions) {
    await expect(action, `${label}: akcja widoczna`).toBeVisible()
    const actionBox = (await action.boundingBox()) as {
      x: number
      y: number
      width: number
      height: number
    }
    expect(actionBox.y, `${label}: akcja zaczyna się w oknie`).toBeGreaterThanOrEqual(0)
    expect(
      actionBox.y + actionBox.height,
      `${label}: akcja w całości w oknie (zasięg kciuka)`,
    ).toBeLessThanOrEqual(vh)
  }
}

/**
 * Długi dialog (k2): pełny ekran na 390 px, a po przewinięciu treści do końca nagłówek
 * i przyciski akcji zostają w widoku (przewija się tylko treść — U12).
 */
async function expectLongDialog(page: Page, label: string, actions: Locator[]): Promise<void> {
  await dialogSettled(page)
  const box = (await paper(page).boundingBox()) as {
    x: number
    y: number
    width: number
    height: number
  }
  const vw = page.viewportSize()?.width ?? 0
  const vh = page.viewportSize()?.height ?? 0
  expect(box.width, `${label}: pełny ekran — szerokość okna`).toBeGreaterThanOrEqual(vw - 1)
  expect(box.height, `${label}: pełny ekran — wysokość okna`).toBeGreaterThanOrEqual(vh - 1)

  // Przewinięcie treści do końca — nagłówek i akcje mają zostać na miejscu.
  const content = paper(page).locator('.MuiDialogContent-root')
  await content.evaluate((el) => {
    el.scrollTop = el.scrollHeight
  })
  const title = paper(page).locator('.MuiDialogTitle-root')
  await expect(title, `${label}: nagłówek widoczny po przewinięciu`).toBeVisible()
  const titleBox = (await title.boundingBox()) as { y: number; height: number }
  expect(titleBox.y, `${label}: nagłówek w oknie po przewinięciu`).toBeGreaterThanOrEqual(0)
  for (const action of actions) {
    await expect(action, `${label}: akcja widoczna po przewinięciu`).toBeVisible()
    const actionBox = (await action.boundingBox()) as { y: number; height: number }
    expect(
      actionBox.y + actionBox.height,
      `${label}: akcja w oknie po przewinięciu (przyklejona stopka)`,
    ).toBeLessThanOrEqual(vh)
  }
}

/** K3 (844×390): krótki dialog mieści się w niskim oknie albo przewija treść; akcje widoczne. */
async function expectLandscapeDialog(page: Page, label: string, actions: Locator[]): Promise<void> {
  await dialogSettled(page)
  const box = (await paper(page).boundingBox()) as {
    x: number
    y: number
    width: number
    height: number
  }
  const vh = page.viewportSize()?.height ?? 0
  expect(box.y, `${label}: dialog zaczyna się w oknie`).toBeGreaterThanOrEqual(0)
  expect(
    box.y + box.height,
    `${label}: dialog mieści się w niskim oknie (treść przewija się w środku)`,
  ).toBeLessThanOrEqual(vh)
  await expectSideMargins(page, label, 16)
  for (const action of actions) {
    await expect(action, `${label}: akcja widoczna`).toBeVisible()
    const actionBox = (await action.boundingBox()) as { y: number; height: number }
    expect(actionBox.y + actionBox.height, `${label}: akcja w oknie`).toBeLessThanOrEqual(vh)
  }
}

/** Szuflada ustawień czatu — po treści nagłówka (wzór: s28-v12-discard). */
function chatDrawer(page: Page): Locator {
  return page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia czatu' })
}

/** Zmiana pola w szufladzie czatu (preset „Kreatywność” → inna wartość; wzór: s28). */
async function changeChatField(page: Page): Promise<void> {
  const drawer = chatDrawer(page)
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
  // Preset przyszedł (formularz brudny, listbox zamknięty) — bez tego pierwsze Esc potrafi
  // zejść na domykający się listbox i dialog „Odrzucić zmiany?” nie otwiera się (bieg T4).
  await expect(preset, 'preset po zmianie').toHaveValue(other as string)
}

/** Koniec animacji wyjścia szuflady — strażnik układu mierzy ekran już po teście (wzór: s28). */
async function drawerGone(drawer: Locator): Promise<void> {
  await expect.poll(async () => await drawer.count()).toBe(0)
}

// ── K1 (390×844): krótkie dialogi ──────────────────────────────────────────────────────────

test('SC-V13-12 k1: usunięcie czatu — dialog dopasowany, nie pełny ekran', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/chats')
  const card = page.getByTestId('chat-card').filter({ hasText: CHAT_NAME }).first()
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: new RegExp(`Menu czatu ${CHAT_NAME}`) }).click()
  await page.getByRole('menuitem', { name: 'Usuń' }).click()
  const dialog = page.getByRole('dialog', { name: 'Usuń czat' })
  await expect(dialog).toBeVisible()
  await expectShortDialog(page, 'usunięcie czatu', [
    dialog.getByRole('button', { name: 'Anuluj' }),
    dialog.getByRole('button', { name: 'Usuń' }),
  ])
  await shot(page, 'sc-v13-12-usuniecie-czatu-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k1 — usunięcie czatu (390)')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
})

test('SC-V13-12 k1: usunięcie bazy wiedzy — dialog dopasowany, nie pełny ekran', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/datasets')
  await page.getByRole('button', { name: new RegExp(`Menu bazy wiedzy ${DATASET_NAME}`) }).click()
  await page.getByRole('menuitem', { name: 'Usuń' }).click()
  const dialog = page.getByRole('dialog', { name: 'Usuń bazę wiedzy' })
  await expect(dialog).toBeVisible()
  await expectShortDialog(page, 'usunięcie bazy', [
    dialog.getByRole('button', { name: 'Anuluj' }),
    dialog.getByRole('button', { name: 'Usuń' }),
  ])
  await shot(page, 'sc-v13-12-usuniecie-bazy-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k1 — usunięcie bazy (390)')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
})

test('SC-V13-12 k1: zmiana nazwy czatu — dialog dopasowany, nie pełny ekran', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/chats')
  const card = page.getByTestId('chat-card').filter({ hasText: CHAT_NAME }).first()
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: new RegExp(`Menu czatu ${CHAT_NAME}`) }).click()
  await page.getByRole('menuitem', { name: 'Zmień nazwę' }).click()
  const dialog = page.getByRole('dialog', { name: 'Zmień nazwę' })
  await expect(dialog).toBeVisible()
  await expectShortDialog(page, 'zmiana nazwy czatu', [
    dialog.getByRole('button', { name: 'Anuluj' }),
    dialog.getByRole('button', { name: 'Zapisz' }),
  ])
  await shot(page, 'sc-v13-12-zmiana-nazwy-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k1 — zmiana nazwy czatu (390)')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
})

test('SC-V13-12 k1: „Nowy czat” — dialog dopasowany, nie pełny ekran', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/chats')
  await page.getByRole('button', { name: 'Utwórz czat' }).click()
  // Tytuł okna tworzenia „Nowy czat” wg makiety SC-10 (T2b); przycisk strony zostaje „Utwórz czat”.
  const dialog = page.getByRole('dialog', { name: 'Nowy czat' })
  await expect(dialog).toBeVisible()
  await expectShortDialog(page, 'nowy czat', [
    dialog.getByRole('button', { name: 'Anuluj' }),
    dialog.getByRole('button', { name: 'Utwórz' }),
  ])
  await shot(page, 'sc-v13-12-nowy-czat-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k1 — nowy czat (390)')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
})

test('SC-V13-12 k1: „Nowy klucz API” — dialog dopasowany, nie pełny ekran', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/user-setting/api')
  await page.getByRole('button', { name: 'Utwórz klucz' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nowy klucz API' })
  await expect(dialog).toBeVisible()
  await expectShortDialog(page, 'nowy klucz API', [
    dialog.getByRole('button', { name: 'Zamknij' }),
    dialog.getByRole('button', { name: 'Utwórz' }),
  ])
  await shot(page, 'sc-v13-12-nowy-klucz-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k1 — nowy klucz API (390)')
  await dialog.getByRole('button', { name: 'Zamknij' }).click()
})

test('SC-V13-12 k1: „Odrzucić zmiany?” — dialog dopasowany, nie pełny ekran', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await expect(chatDrawer(page)).toBeVisible()
  await changeChatField(page)
  await page.keyboard.press('Escape')
  const dialog = page.getByRole('dialog', { name: 'Odrzucić zmiany?' })
  await expect(dialog).toBeVisible()
  await expectShortDialog(page, 'odrzucenie zmian', [
    dialog.getByRole('button', { name: 'Wróć do edycji' }),
    dialog.getByRole('button', { name: 'Odrzuć' }),
  ])
  await shot(page, 'sc-v13-12-odrzuc-zmiany-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k1 — odrzucenie zmian (390)')
  await dialog.getByRole('button', { name: 'Odrzuć' }).click()
  await expect(chatDrawer(page)).toBeHidden()
  await drawerGone(chatDrawer(page))
})

// ── K2 (390×844): długie dialogi — pełny ekran, nagłówek i akcje po przewinięciu ──────────

test('SC-V13-12 k2: import bazy — pełny ekran, nagłówek i akcje w widoku', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/datasets')
  await page.getByRole('button', { name: 'Importuj' }).click()
  const dialog = page.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
  await expect(dialog).toBeVisible()
  await expectLongDialog(page, 'import bazy', [dialog.getByRole('button', { name: 'Anuluj' })])
  await shot(page, 'sc-v13-12-import-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k2 — import bazy (390)')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
})

test('SC-V13-12 k2: eksport bazy — pełny ekran, nagłówek i akcje w widoku', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/datasets')
  await page.getByRole('button', { name: new RegExp(`Menu bazy wiedzy ${DATASET_NAME}`) }).click()
  await page.getByRole('menuitem', { name: 'Eksportuj' }).click()
  const dialog = page.getByRole('dialog', { name: new RegExp(`Eksportuj „${DATASET_NAME}`) })
  await expect(dialog).toBeVisible()
  await expectLongDialog(page, 'eksport bazy', [
    dialog.getByRole('button', { name: 'Anuluj' }),
    dialog.getByRole('button', { name: 'Eksportuj' }),
  ])
  await shot(page, 'sc-v13-12-eksport-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k2 — eksport bazy (390)')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
})

test('SC-V13-12 k2: formularz integracji — pełny ekran, nagłówek i akcje w widoku', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/admin/integrations')
  await page.getByTestId('integration-add').click()
  const dialog = page.getByTestId('integration-form')
  await expect(dialog).toBeVisible()
  await expectLongDialog(page, 'formularz integracji', [
    dialog.getByRole('button', { name: 'Anuluj' }),
    dialog.getByTestId('integration-save'),
  ])
  await shot(page, 'sc-v13-12-integracja-formularz-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k2 — formularz integracji (390)')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(dialog).toBeHidden()
  // Koniec poza siatką integracji (patrz komentarz w teście szczegółów).
  await page.goto('/chats')
})

test('SC-V13-12 k2: szczegóły integracji — pełny ekran, nagłówek i akcje w widoku', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/admin/integrations')
  // Na 390 px siatka jest w trybie kompaktowym (poniżej `md`): akcje to menu ⋮ bez
  // `integration-open-*`, a szczegóły otwiera przycisk nazwy wiersza (kontrakt E4-3c §1).
  const nameButton = page.getByTestId(`integration-name-${integrationId}`)
  await expect(nameButton, 'wiersz integracji na liście').toBeVisible({ timeout: 30_000 })
  await nameButton.click()
  const dialog = page.getByTestId('integration-details')
  await expect(dialog).toBeVisible()
  // Akcje obecne zawsze („Anuluj synchronizację” renderuje się tylko przy aktywnej synchronizacji).
  await expectLongDialog(page, 'szczegóły integracji', [
    dialog.getByTestId('integration-sync'),
    dialog.getByTestId('integration-delete'),
  ])
  await shot(page, 'sc-v13-12-integracja-szczegoly-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k2 — szczegóły integracji (390)')
  await dialog.getByRole('button', { name: 'Zamknij' }).click()
  await expect(dialog).toBeHidden()
  // Koniec na ekranie bez siatki integracji: poziome przycięcie przycisku nazwy w kompaktowej
  // siatce na 390 px to odziedziczony defekt tego ekranu (poza zakresem T1b — raport dla TL/T4),
  // nie zachowanie dialogów ze SC-V13-12.
  await page.goto('/chats')
})

// ── K3 (844×390): poziomo — krótkie dialogi mieszczą się albo przewijają, akcje widoczne ───

test('SC-V13-12 k3: poziomo 844×390 — krótkie dialogi mieszczą się, akcje widoczne', async ({
  page,
}) => {
  await page.setViewportSize({ width: 844, height: 390 })

  // Usunięcie czatu.
  await page.goto('/chats')
  const card = page.getByTestId('chat-card').filter({ hasText: CHAT_NAME }).first()
  // Pierwsze ładowanie listy bywa > 5 s (znany flak z T1b) — zapas jak dla wiersza integracji.
  await expect(card).toBeVisible({ timeout: 30_000 })
  await card.getByRole('button', { name: new RegExp(`Menu czatu ${CHAT_NAME}`) }).click()
  await page.getByRole('menuitem', { name: 'Usuń' }).click()
  const deleteDialog = page.getByRole('dialog', { name: 'Usuń czat' })
  await expect(deleteDialog).toBeVisible()
  await expectLandscapeDialog(page, 'usunięcie czatu (poziomo)', [
    deleteDialog.getByRole('button', { name: 'Anuluj' }),
    deleteDialog.getByRole('button', { name: 'Usuń' }),
  ])
  await shot(page, 'sc-v13-12-usuniecie-czatu-poziomo')
  await expectNoLayoutDefects(page, 'SC-V13-12 k3 — usunięcie czatu (poziomo)')
  await deleteDialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(deleteDialog).toBeHidden()

  // „Nowy czat”.
  await page.getByRole('button', { name: 'Utwórz czat' }).click()
  const createDialog = page.getByRole('dialog', { name: 'Nowy czat' })
  await expect(createDialog).toBeVisible()
  await expectLandscapeDialog(page, 'nowy czat (poziomo)', [
    createDialog.getByRole('button', { name: 'Anuluj' }),
    createDialog.getByRole('button', { name: 'Utwórz' }),
  ])
  await expectNoLayoutDefects(page, 'SC-V13-12 k3 — nowy czat (poziomo)')
  await createDialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(createDialog).toBeHidden()

  // „Odrzucić zmiany?”.
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await expect(chatDrawer(page)).toBeVisible()
  await changeChatField(page)
  await page.keyboard.press('Escape')
  const discardDialog = page.getByRole('dialog', { name: 'Odrzucić zmiany?' })
  await expect(discardDialog).toBeVisible()
  await expectLandscapeDialog(page, 'odrzucenie zmian (poziomo)', [
    discardDialog.getByRole('button', { name: 'Wróć do edycji' }),
    discardDialog.getByRole('button', { name: 'Odrzuć' }),
  ])
  await expectNoLayoutDefects(page, 'SC-V13-12 k3 — odrzucenie zmian (poziomo)')
  await discardDialog.getByRole('button', { name: 'Odrzuć' }).click()
  await expect(chatDrawer(page)).toBeHidden()
  await drawerGone(chatDrawer(page))
})

// ── Dopiski T1b (T4): usunięcie PLIKU, długa nazwa w potwierdzeniu, obrót z otwartym
//    dialogiem, siatka integracji 390 px bez wad układu (U3) ────────────────────────────────

test('SC-V13-12 k1: usunięcie pliku — dialog dopasowany, nie pełny ekran', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/files')
  const row = page.getByRole('row').filter({ hasText: FILE_NAME }).first()
  await expect(row, 'wiersz pliku na liście').toBeVisible({ timeout: 30_000 })
  // Kompaktowa siatka (< md): akcje jako menu ⋮ w pierwszej kolumnie (kontrakt E3-7 §C2).
  await row.getByTestId('row-actions-menu').click()
  await page.getByRole('menuitem', { name: 'Usuń' }).click()
  const dialog = page.getByRole('dialog', { name: 'Usuń pliki' })
  await expect(dialog).toBeVisible()
  await expectShortDialog(page, 'usunięcie pliku', [
    dialog.getByRole('button', { name: 'Anuluj' }),
    dialog.getByRole('button', { name: 'Usuń' }),
  ])
  await shot(page, 'sc-v13-12-usuniecie-pliku-390')
  await expectNoLayoutDefects(page, 'SC-V13-12 k1 — usunięcie pliku (390)')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(dialog).toBeHidden()
})

test('SC-V13-12: długa nazwa w potwierdzeniu — zawinięta, bez poziomego przepełnienia', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/chats')
  const card = page.getByTestId('chat-card').filter({ hasText: LONG_CHAT_NAME }).first()
  await expect(card, 'karta czatu o długiej nazwie').toBeVisible()
  await card
    .getByRole('button', { name: new RegExp(`Menu czatu ${LONG_CHAT_NAME.slice(0, 40)}`) })
    .click()
  await page.getByRole('menuitem', { name: 'Usuń' }).click()
  const dialog = page.getByRole('dialog', { name: 'Usuń czat' })
  await expect(dialog).toBeVisible()
  await expectShortDialog(page, 'długa nazwa w potwierdzeniu', [
    dialog.getByRole('button', { name: 'Anuluj' }),
    dialog.getByRole('button', { name: 'Usuń' }),
  ])
  // U2: komunikat z nazwą bez spacji zawija się (overflow-wrap: anywhere) — papier dialogu
  // nie przewija się w poziomie (scrollWidth == clientWidth, tolerancja zaokrągleń).
  const horizontalOverflow = await paper(page).evaluate((el) => el.scrollWidth - el.clientWidth)
  expect(
    horizontalOverflow,
    'długa nazwa zawinięta — brak poziomego przewijania papieru',
  ).toBeLessThanOrEqual(1)
  await expectNoLayoutDefects(page, 'SC-V13-12 — długa nazwa w potwierdzeniu (390)')
  // Potwierdzenie kasuje czat (sprzątanie w teście; afterAll jest awaryjne).
  await dialog.getByRole('button', { name: 'Usuń' }).click()
  await expect(dialog).toBeHidden()
  longNameChatId = ''
})

test('SC-V13-12 k3: obrót 844×390 z otwartym dialogiem — mieści się, akcje widoczne', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/chats')
  const card = page.getByTestId('chat-card').filter({ hasText: CHAT_NAME }).first()
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: new RegExp(`Menu czatu ${CHAT_NAME}`) }).click()
  await page.getByRole('menuitem', { name: 'Usuń' }).click()
  const dialog = page.getByRole('dialog', { name: 'Usuń czat' })
  await expect(dialog).toBeVisible()
  await dialogSettled(page)
  // Obrót urządzenia przy OTWARTYM dialogu: marginesy i akcje muszą się pomieścić.
  await page.setViewportSize({ width: 844, height: 390 })
  await expectLandscapeDialog(page, 'usunięcie czatu po obrocie', [
    dialog.getByRole('button', { name: 'Anuluj' }),
    dialog.getByRole('button', { name: 'Usuń' }),
  ])
  await expectNoLayoutDefects(page, 'SC-V13-12 k3 — obrót z otwartym dialogiem')
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(dialog).toBeHidden()
})

test('SC-V13-12: siatka integracji 390 px — przycisk nazwy nieprzycięty (U3)', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/admin/integrations')
  const nameButton = page.getByTestId(`integration-name-${integrationId}`)
  await expect(nameButton, 'wiersz integracji na liście').toBeVisible({ timeout: 30_000 })
  // Defekt z T1b (cut-off 87% na button[integration-name-*]): kompaktowa siatka po naprawie
  // (wielokropek + przyklejona kolumna nazwy) przechodzi strażnik układu na tym ekranie.
  await expectNoLayoutDefects(page, 'SC-V13-12 — siatka integracji (390)')
  // U2: wielokropek z pełną nazwą w podpowiedzi.
  const title = await nameButton.getAttribute('title')
  expect(title, 'pełna nazwa w podpowiedzi przycisku').toBe(INTEGRATION_NAME)
})
