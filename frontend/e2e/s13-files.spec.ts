// Scenariusz S6-13 (08 §7.10; BRIEF E4-5c pkt 8, kontrakt WP E4-5c §8): menedżer plików —
// wejście z menu „Pliki”, nowy folder, wejście do folderu po breadcrumbach, upload pliku
// do podfolderu, wyszukiwanie po nazwie, zmiana nazwy utrwalona po F5, przeniesienie do roota,
// połączenie z datasetem utworzonym w teście (chip w kolumnie „Datasety” i dokument w zakładce
// Pliki datasetu), pobranie (zdarzenie `download` z nazwą pliku) i usunięcie zbiorcze
// z potwierdzeniem. Backend nie jest mockowany — te same trasy woła UI, a resztki danych
// sprząta `test.afterAll` przez API (`helpers/files.ts`).
import type { Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { expectNoSeriousA11y } from './helpers/axe'
import { apiLogin, createDataset, loginViaUi } from './helpers'
import { createUserViaUi, deleteUserByEmail, loginViaUiAs } from './helpers/admin'
import { deleteAllFiles, deleteDataset } from './helpers/files'
import { setProfileLanguage } from './helpers/models'

const DATASET_NAME = 'E2E S6-13 baza'
const FOLDER_NAME = 'Projekty e2e'
const FILE_NAME = 'e2e-s13.txt'
const RENAMED_NAME = 'e2e-s13-nowa.txt'
const SECOND_NAME = 'e2e-s13-b.txt'
const FILE_BODY = 'Treść pliku e2e S6-13'

/** Wiersz DataGrid z daną nazwą pliku/folderu (nagłówek nie zawiera tekstu wiersza). */
function rowByText(page: Page, text: string) {
  return page.getByRole('row').filter({ hasText: text })
}

/** Wiersz dokumentu w zakładce Pliki datasetu (wzór: `s03-upload-parse.spec.ts`) — nazwa to link. */
function documentRow(page: Page, name: string) {
  return page.getByRole('row').filter({ has: page.getByRole('link', { name }) })
}

/** Upload jednego pliku tekstowego z bieżącego folderu („Dodaj” → „Prześlij plik”). */
async function uploadFile(page: Page, name: string): Promise<void> {
  await page.getByTestId('files-add').click()
  await page.getByTestId('files-add-upload').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await page.getByTestId('files-upload-input').setInputFiles({
    name,
    mimeType: 'text/plain',
    buffer: Buffer.from(FILE_BODY),
  })
  // Zakończenie żądania multipart: pozycja listy dostaje stan „done” (nazwa z `files.upload.done`).
  await expect(dialog.getByText('Przesłano', { exact: true })).toBeVisible()
  await page.getByTestId('files-upload-close').click()
  await expect(dialog).toBeHidden()
}

/** Dane scenariusza potrzebne sprzątaniu; brak, gdy test padł przed ich utworzeniem. */
let cleanup: { token: string; datasetId: string } | undefined

test.afterAll(async ({ request }) => {
  if (cleanup === undefined) return
  await deleteAllFiles(request, cleanup.token)
  await deleteDataset(request, cleanup.token, cleanup.datasetId)
})

test('S6-13: foldery, upload, szukanie, rename, przenoszenie, link, pobranie, usunięcie', async ({
  page,
  request,
}) => {
  // Reset, logowanie, kilka dialogów i odświeżeń po F5 — zapas ponad domyślne 30 s.
  test.setTimeout(180_000)

  // 1. Reset (root pusty) i baza wiedzy do kroku „Połącz z datasetem”.
  await resetDb(request)
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, DATASET_NAME)
  cleanup = { token, datasetId }
  await loginViaUi(page)

  // 2. Wejście z menu; root jest pusty po resecie, więc widać stan pusty.
  await page.getByRole('navigation').getByRole('link', { name: 'Pliki' }).click()
  await expect(page).toHaveURL(/\/files/)
  await expect(page.getByTestId('empty-state')).toBeVisible()

  // 3. Nowy folder w rootcie.
  await page.getByTestId('files-add').click()
  await page.getByTestId('files-add-folder').click()
  const folderDialog = page.getByRole('dialog')
  await folderDialog.getByTestId('files-folder-name').fill(FOLDER_NAME)
  await folderDialog.getByTestId('files-folder-create').click()
  await expect(folderDialog).toBeHidden()
  await expect(rowByText(page, FOLDER_NAME)).toBeVisible()

  // 4. Wejście do folderu: klik nazwy (folder to przycisk) → `?folder=`, breadcrumbs z nazwą.
  await rowByText(page, FOLDER_NAME).getByRole('button', { name: FOLDER_NAME }).click()
  await expect(page).toHaveURL(/folder=/)
  const crumbs = page.getByTestId('files-breadcrumbs')
  await expect(crumbs).toContainText('Pliki')
  await expect(crumbs).toContainText(FOLDER_NAME)

  // 5. Upload do podfolderu.
  await uploadFile(page, FILE_NAME)
  await expect(rowByText(page, FILE_NAME)).toBeVisible()

  // Jasny motyw, główny ekran scenariusza: menedżer plików wewnątrz folderu z wgranym plikiem.
  await expectNoSeriousA11y(page, 'S6-13 menedżer plików — folder z plikiem')

  // 6. Wyszukiwanie: trafienie, brak wyników (stan pusty), wyczyszczenie pola.
  const search = page.getByTestId('files-search').getByRole('textbox')
  await search.fill('s13')
  await expect(rowByText(page, FILE_NAME)).toBeVisible()
  await search.fill('brak-takiego')
  await expect(page.getByTestId('empty-state')).toContainText('Brak wyników wyszukiwania.')
  await search.fill('')
  await expect(rowByText(page, FILE_NAME)).toBeVisible()

  // 7. Zmiana nazwy; F5 potwierdza utrwalenie na backendzie.
  await rowByText(page, FILE_NAME).getByRole('button', { name: 'Zmień nazwę' }).click()
  const renameDialog = page.getByRole('dialog')
  await renameDialog.getByTestId('files-rename-name').fill(RENAMED_NAME)
  await renameDialog.getByTestId('files-rename-save').click()
  await expect(rowByText(page, RENAMED_NAME)).toBeVisible()
  await page.reload()
  await expect(rowByText(page, RENAMED_NAME)).toBeVisible()

  // 8. Przeniesienie do roota drzewem dialogu; folder pusty, plik widoczny po wyjściu breadcrumbs.
  await rowByText(page, RENAMED_NAME).getByRole('button', { name: 'Przenieś' }).click()
  const moveDialog = page.getByRole('dialog')
  await moveDialog.getByTestId('folder-node-__root__').click()
  await moveDialog.getByTestId('files-move-confirm').click()
  await expect(moveDialog).toBeHidden()
  await expect(page.getByTestId('empty-state')).toContainText('Brak plików')
  await crumbs.getByRole('button', { name: 'Pliki' }).click()
  await expect(page).not.toHaveURL(/folder=/)
  await expect(rowByText(page, RENAMED_NAME)).toBeVisible()

  // 9. Połączenie z datasetem: chip w kolumnie „Datasety” i dokument w zakładce Pliki datasetu.
  await rowByText(page, RENAMED_NAME).getByRole('button', { name: 'Połącz z datasetem' }).click()
  const linkDialog = page.getByRole('dialog')
  await linkDialog.getByRole('checkbox', { name: DATASET_NAME }).check()
  await linkDialog.getByTestId('files-link-confirm').click()
  await expect(linkDialog).toBeHidden()
  await expect(rowByText(page, RENAMED_NAME).getByTestId('files-kb-chip')).toContainText(
    DATASET_NAME,
  )
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible()
  await expect(documentRow(page, RENAMED_NAME)).toBeVisible()
  // T15: tabela mieści się w oknie na desktopie (1280) — brak fałszywego cienia przewijania
  // z nadmiaru separatora ostatniej kolumny MUI X; cień przy realnym przewijaniu (390) pilnuje
  // SC-E5-H9-07 w s24-h9-b.spec.ts.
  await expect(page.getByTestId('scroll-shadow-right')).toHaveCount(0)

  // 10. Pobranie: zdarzenie `download` z nazwą pliku z `Content-Disposition`.
  await page.goto('/files')
  await expect(rowByText(page, RENAMED_NAME)).toBeVisible()
  // T15: menedżer plików na desktopie — tabela się mieści, fałszywy cień nie może się pojawić.
  await expect(page.getByTestId('scroll-shadow-right')).toHaveCount(0)
  const downloadPromise = page.waitForEvent('download')
  await rowByText(page, RENAMED_NAME).getByRole('button', { name: 'Pobierz' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename(), 'nazwa pobranego pliku').toBe(RENAMED_NAME)

  // 11. Usunięcie zbiorcze: drugi plik, zaznaczenie obu wierszy, potwierdzenie; zostaje folder.
  await uploadFile(page, SECOND_NAME)
  await expect(rowByText(page, SECOND_NAME)).toBeVisible()
  await rowByText(page, RENAMED_NAME).getByRole('checkbox').check()
  await rowByText(page, SECOND_NAME).getByRole('checkbox').check()
  await page.getByTestId('files-bulk-delete').click()
  const confirmDialog = page.getByRole('dialog')
  await confirmDialog.getByRole('button', { name: 'Usuń' }).click()
  await expect(confirmDialog).toBeHidden()
  const grid = page.getByTestId('files-grid')
  await expect(grid.getByRole('row').filter({ hasText: '.txt' })).toHaveCount(0)
  await expect(rowByText(page, FOLDER_NAME)).toBeVisible()
})

// M2 (QA E5-H9-2): kolumna Data mieści datę w EN („Oct 12, 2026, 4:47 AM” — ~177 px treści)
// przy 1440 px, bez ucięcia. Osobne konto z językiem EN w profilu (profil nadpisuje locale,
// DEC-306) — nie przełączamy języka konta z seedu, bo współdzielą go inne pliki biegu
// (przebieg 2a QA: tak powstał artefakt D1 „UI po EN mimo wd.language=pl”).
test.describe('kolumna Data w EN przy 1440 px (M2)', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  const M2_PASSWORD = 'wd-test-s13-m2'
  const email = `s13-m2-${Date.now()}@wd.test`
  const FILE_NAME_M2 = 'e2e-s13-m2.txt'

  test('data EN mieści się w kolumnie bez ucięcia', async ({ page, request }) => {
    test.setTimeout(120_000)
    const adminToken = await apiLogin(request)

    // Konto użytkownika zakładane przez admina w UI; plik wgramy jego tokenem (własny root).
    await loginViaUi(page)
    await page.getByRole('navigation').getByRole('link', { name: 'Administracja' }).click()
    await expect(page).toHaveURL(/\/admin\/users$/)
    await createUserViaUi(page, { email, password: M2_PASSWORD, nickname: 'S13 M2' })

    // Język profilu EN przez API, upload pliku tokenem nowego konta.
    const login = await request.post(`${process.env.WD_E2E_API_URL}/api/v1/auth/login`, {
      data: { email, password: M2_PASSWORD },
    })
    expect(login.status(), 'logowanie nowego konta').toBe(200)
    const userToken = ((await login.json()) as { data: { access_token: string } }).data.access_token
    await setProfileLanguage(request, userToken, 'en')
    const upload = await request.post(`${process.env.WD_E2E_API_URL}/api/v1/files`, {
      headers: { authorization: `Bearer ${userToken}` },
      multipart: {
        file: {
          name: FILE_NAME_M2,
          mimeType: 'text/plain',
          buffer: Buffer.from(FILE_BODY),
        },
      },
    })
    expect(upload.status(), 'upload pliku nowego konta').toBe(200)

    // UI konta EN (profil wygrywa z locale przeglądarki): data w formacie EN.
    await page.getByRole('button', { name: 'Menu użytkownika' }).click()
    await page.getByRole('menuitem', { name: 'Wyloguj' }).click()
    await expect(page).toHaveURL(/\/login/)
    await loginViaUiAs(page, email, M2_PASSWORD)
    await page.goto('/files')
    const dateCell = rowByText(page, FILE_NAME_M2).locator('[data-field="update_time"]')
    await expect(dateCell).toBeVisible()
    await expect(dateCell, 'format daty EN').toContainText(/(AM|PM)/)
    await page.evaluate(() => document.fonts.ready)
    const widths = await dateCell.evaluate((cell: HTMLElement) => ({
      scroll: cell.scrollWidth,
      client: cell.clientWidth,
    }))
    expect(
      widths.scroll,
      `M2: data EN mieści się w kolumnie (scrollWidth ${widths.scroll} > clientWidth ${widths.client})`,
    ).toBeLessThanOrEqual(widths.client + 1)

    // Sprzątanie konta (kaskada usuwa i jego pliki).
    await deleteAllFiles(request, userToken)
    await deleteUserByEmail(request, adminToken, email)
  })
})
