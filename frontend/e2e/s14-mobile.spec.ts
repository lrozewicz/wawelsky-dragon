// Scenariusz S6-14 (08 §7.10, kontrakt WP E3-7 §C2): wzorzec < md — na ekranie telefonu
// (390×844) akcje wiersza są widoczne od razu jako menu ⋮ w pierwszej kolumnie, bez przewijania
// poziomego. Sprawdzamy to dla menedżera Plików i dla zakładki Pliki datasetu. Backend nie jest
// mockowany — te same trasy woła UI, a resztki sprząta `test.afterAll` przez API.
import type { Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { expectNoSeriousA11y } from './helpers/axe'
import { apiLogin, createDataset, loginViaUi } from './helpers'
import { deleteAllFiles, deleteDataset } from './helpers/files'

const DATASET_NAME = 'E2E S6-14 baza'
const FOLDER_NAME = 'Projekty mobile'
const DOC_NAME = 'e2e-s14.txt'
const DOC_BODY = 'Treść pliku e2e S6-14'

test.use({ viewport: { width: 390, height: 844 } })

/** Wiersz DataGrid z danym tekstem (nagłówek nie zawiera tekstu wiersza). */
function rowByText(page: Page, text: string) {
  return page.getByRole('row').filter({ hasText: text })
}

/** Wiersz dokumentu w zakładce Pliki datasetu — nazwa jest linkiem. */
function documentRow(page: Page, name: string) {
  return page.getByRole('row').filter({ has: page.getByRole('link', { name }) })
}

/**
 * Nazwa wiersza w oknie obok menu ⋮ (kontrakt WP E3-H4 p. 3): przy 390 px kolumny drugorzędne
 * (data, rozmiar, datasety) wychodzą poza ekran, ale nazwa pliku/folderu ma pozostać widoczna
 * bez przewijania siatki.
 */
async function assertRowName(row: ReturnType<typeof rowByText>, name: string): Promise<void> {
  await expect(row.getByText(name)).toBeInViewport()
}

/** Nawigacja mobilna: hamburger w nagłówku → „Pliki” w szufladzie. */
async function openFilesPage(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Otwórz menu' }).click()
  await page.getByRole('navigation').getByRole('link', { name: 'Pliki' }).click()
  await expect(page).toHaveURL(/\/files/)
}

/**
 * Wzorzec < md: przycisk ⋮ jest w oknie bez przewijania poziomego, a menu pokazuje akcję
 * zmiany nazwy; Esc zamyka menu.
 */
async function assertRowMenu(page: Page, row: ReturnType<typeof rowByText>): Promise<void> {
  const menu = row.getByTestId('row-actions-menu')
  await expect(menu).toBeInViewport()
  await menu.click()
  await expect(page.getByTestId('row-action-rename')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('row-action-rename')).toBeHidden()
}

/** Dane scenariusza potrzebne sprzątaniu; brak, gdy test padł przed ich utworzeniem. */
let cleanup: { token: string; datasetId: string } | undefined

test.afterAll(async ({ request }) => {
  if (cleanup === undefined) return
  await deleteAllFiles(request, cleanup.token)
  await deleteDataset(request, cleanup.token, cleanup.datasetId)
})

test('S6-14 mobile', async ({ page, request }) => {
  // Reset, logowanie i kilka odświeżeń listy po uploadzie — zapas ponad domyślne 30 s.
  test.setTimeout(120_000)

  // 1. Reset i baza wiedzy (zakładka Pliki datasetu ma mieć dokument do akcji wiersza).
  await resetDb(request)
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, DATASET_NAME)
  cleanup = { token, datasetId }
  await loginViaUi(page)

  // 2. Menedżer Plików przez szufladę mobilną; root pusty po resecie.
  await openFilesPage(page)
  await expect(page.getByTestId('empty-state')).toBeVisible()

  // 3. Nowy folder przez UI (jak S6-13) — daje wiersz do sprawdzenia menu.
  await page.getByTestId('files-add').click()
  await page.getByTestId('files-add-folder').click()
  const folderDialog = page.getByRole('dialog')
  await folderDialog.getByTestId('files-folder-name').fill(FOLDER_NAME)
  await folderDialog.getByTestId('files-folder-create').click()
  await expect(folderDialog).toBeHidden()
  await expect(rowByText(page, FOLDER_NAME)).toBeVisible()

  // Kontrakt §C5: axe na ekranie listy Plików przy 390 px (wzorzec < md — menu ⋮ w pierwszej
  // kolumnie, bez poziomego przewijania).
  await expectNoSeriousA11y(page, 'S6-14 pliki mobile 390px')

  // 4. Wzorzec < md w liście Plików: menu ⋮ w pierwszej kolumnie, widoczne bez przewijania,
  // a obok niego nazwa folderu.
  const folderRow = rowByText(page, FOLDER_NAME)
  await assertRowName(folderRow, FOLDER_NAME)
  await assertRowMenu(page, folderRow)

  // 5. Zakładka Pliki datasetu: dokument przez UI, potem ten sam wzorzec w wierszu dokumentu.
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()
  await page.getByTestId('files-add').click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog).toBeVisible()
  await page.getByTestId('upload-input').setInputFiles({
    name: DOC_NAME,
    mimeType: 'text/plain',
    buffer: Buffer.from(DOC_BODY),
  })
  await page.getByTestId('upload-start').click()
  await expect(uploadDialog.getByText('Przesłano', { exact: true })).toBeVisible()
  await uploadDialog.getByRole('button', { name: 'Gotowe' }).click()
  await expect(uploadDialog).toBeHidden()
  await expect(documentRow(page, DOC_NAME)).toBeVisible()

  // 6. Ten sam wzorzec w zakładce Pliki datasetu: nazwa dokumentu widoczna obok menu ⋮.
  const docRow = documentRow(page, DOC_NAME)
  await assertRowName(docRow, DOC_NAME)
  await assertRowMenu(page, docRow)
})

// U6 (kontrakt WP E5-H6a §C2, p. 5): na 390 px każdą z czterech zakładek panelu admina można
// doprowadzić do widoku i kliknąć. Usterka z QA: „Status systemu” wystawało poza krawędź, bo MUI
// domyślnie ukrywa przyciski przewijania paska zakładek poniżej progu `sm` (600 px).
test('S6-14 U6: wszystkie zakładki admina dostępne na 390 px', async ({ page }) => {
  test.setTimeout(60_000)
  await loginViaUi(page)

  // Mobilna szuflada: hamburger → „Administracja” (jak `openFilesPage`).
  await page.getByRole('button', { name: 'Otwórz menu' }).click()
  await page.getByRole('navigation').getByRole('link', { name: 'Administracja' }).click()
  await expect(page).toHaveURL(/\/admin\/users$/)

  // Dostępność zakładek na telefonie strzeże zawijanie do kolejnych rzędów (SC-E5-H8z-03):
  // przyciski przewijania wyłączone — rezerwowały ~40 px pustki przed pierwszą zakładką.
  // Osiągalność każdej zakładki pilnuje pętla poniżej i SC-E5-H8d-03 (s18-layout-fixes).

  const viewport = page.viewportSize()
  expect(viewport, 'viewport').not.toBeNull()

  const tabs = [
    { testId: 'admin-tab-users', path: /\/admin\/users$/ },
    { testId: 'admin-tab-access', path: /\/admin\/access$/ },
    { testId: 'admin-tab-status', path: /\/admin\/status$/ },
    { testId: 'admin-tab-integrations', path: /\/admin\/integrations$/ },
  ]

  for (const { testId, path } of tabs) {
    const tab = page.getByTestId(testId)
    await expect(tab).toBeVisible()
    await tab.click()
    await expect(page).toHaveURL(path)
    // Najpierw klik (zakładka staje się AKTYWNA — MUI nie cofa wtedy przewijania), a geometrię
    // ustalamy pętlą: `inline: 'center'` wymusza pełną widoczność (MUI potrafi samo nie doscrollować
    // do aktywnej zakładki), a `poll` odpornie czeka na ustabilizowanie pozycji.
    await expect
      .poll(
        async () => {
          await tab.evaluate((element) =>
            element.scrollIntoView({ block: 'nearest', inline: 'center' }),
          )
          const box = await tab.boundingBox()
          return box !== null && box.x >= 0 && box.x + box.width <= viewport!.width
        },
        { message: `${testId}: cała zakładka w szerokości viewportu` },
      )
      .toBe(true)
  }
})
