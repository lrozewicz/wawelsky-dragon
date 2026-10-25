// Scenariusze SC-E67-z2-19…23 (work/wp/E67-z2/SCENARIOS.md, brief T7): język konta zapisany do
// `wd.language`, jasne komunikaty błędów importu, czas utworzenia eksportu z sekundami, awatar
// bazy „X (import …)” z jedną literą, nazwa klucza API na liście.
// Testy pisane PRZED poprawkami (czerwone z właściwej przyczyny). Wzorce: s26-e67a-feedback-taskbar
// (zasiew paska zadań), s27-e67b-sc07 (login bez sesji), s26-e67a-import (upuszczenie paczki).
import type { APIRequestContext, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createDataset, loginViaUi } from './helpers'
import { dropFile } from './helpers/dnd'
import { deleteDataset } from './helpers/files'
import { fakePackageBytes, zipStore } from './helpers/kbTransfer'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { deleteApiToken } from './helpers/settings'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const DESKTOP = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }
const SHOTS = process.env.WD_SHOTS_DIR ?? ''
const NO_SESSION = { cookies: [], origins: [] }

let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

const session = uiSession('s27-e67z2-e')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(180_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

const cleanupDatasets: string[] = []
const cleanupTokens: string[] = []
test.afterEach(async ({ context, request }) => {
  const token = await adminToken(request)
  for (const id of cleanupDatasets.splice(0)) await deleteDataset(request, token, id)
  for (const key of cleanupTokens.splice(0)) await deleteApiToken(request, token, key)
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

// --- SC-E67-z2-20 ------------------------------------------------------------------------

/** Upuszcza bajty w dialogu importu i zwraca tekst wszystkich alertów błędów paczki. */
async function dropAndReadErrors(page: Page, bytes: Buffer, name: string): Promise<string> {
  await page.goto('/datasets')
  await page.getByRole('button', { name: 'Importuj' }).click()
  const dialog = page.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
  await expect(dialog).toBeVisible()
  await dropFile(page, dialog.getByTestId('kb-import-dropzone'), bytes, name, 'application/zip')
  const invalid = dialog.getByTestId('kb-import-invalid')
  await expect(invalid).toBeVisible({ timeout: 60_000 })
  await expectNoLayoutDefects(page, 'SC-E67-z2-20 lista błędów paczki')
  return invalid.innerText()
}

test('SC-E67-z2-20 import: plik nie-ZIP — jasny komunikat bez angielskiego ogona', async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  const text = await dropAndReadErrors(page, fakePackageBytes(), 'nie-paczka.wdkb.zip')
  await shot(page, 'z2-20-garbage-1280')
  expect(text).toContain('To nie jest poprawna paczka bazy wiedzy (.wdkb.zip).')
  expect(text).not.toMatch(/File is not a zip file|archiwum ZIP:/)
})

test('SC-E67-z2-20 import: ZIP bez manifestu — „To nie jest paczka bazy wiedzy Wawelsky Dragon”, nie „Niebezpieczna ścieżka”', async ({
  page,
}) => {
  await page.setViewportSize(MOBILE)
  const zip = zipStore([{ name: 'a.txt', data: Buffer.from('nic', 'utf8') }])
  const text = await dropAndReadErrors(page, zip, 'bez-manifestu.wdkb.zip')
  await shot(page, 'z2-20-nomanifest-390')
  expect(text).toContain(
    'To nie jest paczka bazy wiedzy Wawelsky Dragon (brak pliku manifest.json).',
  )
  expect(text).not.toContain('Niebezpieczna ścieżka')
})

// --- SC-E67-z2-21 ------------------------------------------------------------------------

test('SC-E67-z2-21 dwa eksporty z tej samej minuty mają rozróżnialny czas (z sekundami)', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const me = await request.get(`${API_URL}/api/v1/users/me`, {
    headers: { authorization: `Bearer ${token}` },
  })
  const userId = ((await me.json()) as { data: { id: string } }).data.id
  const minute = Math.floor(Date.now() / 60_000) * 60_000
  const exportTask = (id: string, createdAt: number): Record<string, unknown> => ({
    task_id: id,
    kind: 'export',
    dataset_id: null,
    status: 'done',
    stage: null,
    done: 100,
    total: 100,
    progress: 1,
    message: 'done',
    error: null,
    created_at: createdAt,
    finished_at: null,
    result: {
      download_url: `/api/wd/v1/exports/${id}/download?sig=x`,
      expires_at: minute + 3_600_000,
      size_bytes: 1_048_576,
      file_name: `${id}.wdkb.zip`,
    },
  })
  const rows = [
    { id: 't-z21a', at: minute + 5_000 },
    { id: 't-z21b', at: minute + 35_000 },
  ].map(({ id, at }) => ({
    task_id: id,
    kind: 'export',
    label: `Baza ${id}`,
    dataset_id: null,
    added_at: Date.now() - 60_000,
    last: exportTask(id, at),
  }))
  await page.addInitScript(
    ({ key, value }) => {
      if (localStorage.getItem(`${key}:seeded`) === null) {
        localStorage.setItem(key, value)
        localStorage.setItem(`${key}:seeded`, '1')
      }
    },
    { key: `wd.kbTasks.v1:${userId}`, value: JSON.stringify(rows) },
  )
  await page.setViewportSize(DESKTOP)
  await page.goto('/datasets')
  const rowA = page.locator('[data-task-id="t-z21a"]')
  const rowB = page.locator('[data-task-id="t-z21b"]')
  await expect(rowA).toBeVisible()
  await expect(rowB).toBeVisible()
  await shot(page, 'z2-21-exports-1280')
  const created = async (row: typeof rowA): Promise<string> =>
    /utworzono\s+([^\n]+)/.exec(await row.innerText())?.[1]?.trim() ?? ''
  const [a, b] = [await created(rowA), await created(rowB)]
  expect(a, 'czas z sekundami (HH:mm:ss)').toMatch(/\d{1,2}:\d{2}:\d{2}/)
  expect(b, 'czas z sekundami (HH:mm:ss)').toMatch(/\d{1,2}:\d{2}:\d{2}/)
  expect(a, 'wiersze z tej samej minuty są rozróżnialne').not.toBe(b)
  await expectNoLayoutDefects(page, 'SC-E67-z2-21 lista eksportów 1280')
})

// --- SC-E67-z2-22 ------------------------------------------------------------------------

test('SC-E67-z2-22 awatar bazy „E67-GUS (import …)” to jedna litera, nie „E(”', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const id = await createDataset(request, token, `E67-GUS (import ${Date.now()})`)
  cleanupDatasets.push(id)
  await page.setViewportSize(DESKTOP)
  await page.goto(`/dataset/files/${id}`)
  const avatar = page.locator('.MuiAvatar-root').filter({ hasText: /\S/ }).first()
  await expect(avatar).toBeVisible()
  await expect(avatar).toHaveText('E')
  await shot(page, 'z2-22-avatar-1280')
  await expectNoLayoutDefects(page, 'SC-E67-z2-22 nagłówek bazy')
})

// --- SC-E67-z2-23 ------------------------------------------------------------------------

test('SC-E67-z2-23 nazwa klucza API widoczna na liście (1280, 390)', async ({ page }) => {
  // Kontrakt od v1.2: `GET /api/v1/system/tokens` zwraca `name` (K20 §1), więc kolumna Nazwa
  // może pokazać nazwę klucza tuż po utworzeniu przez dialog (krok użytkownika).
  const keyName = `Klucz z2-23 z12-${Date.now()}`
  await page.setViewportSize(DESKTOP)
  await page.goto('/user-setting/api')
  await page.getByRole('button', { name: 'Utwórz klucz' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nowy klucz API' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('textbox', { name: 'Nazwa (opcjonalna)' }).fill(keyName)
  await dialog.getByRole('button', { name: 'Utwórz', exact: true }).click()
  const secret = ((await dialog.getByTestId('settings-new-token').textContent()) ?? '').trim()
  cleanupTokens.push(secret)
  await dialog.getByRole('button', { name: 'Zamknij', exact: true }).click()
  await expect(dialog).toHaveCount(0)

  // 1280: wiersz z nazwą klucza na liście.
  const grid = page.getByRole('grid', { name: 'Klucze API' })
  await expect(grid.getByRole('gridcell').filter({ hasText: keyName })).toBeVisible()
  await shot(page, 'z2-23-keys-1280')

  // 390: komórka nadal widoczna, pełna nazwa w `title` (wielokropek CSS), bez wad układu.
  await page.setViewportSize(MOBILE)
  await expect(grid.getByRole('gridcell').filter({ hasText: keyName })).toHaveAttribute(
    'title',
    keyName,
  )
  await shot(page, 'z2-23-keys-390')
  await expectNoLayoutDefects(page, 'SC-E67-z2-23 klucze API 390')
})

// --- SC-E67-z2-19 (ostatni: wylogowanie unieważnia cookie sesji pliku) --------------------

test.describe('SC-E67-z2-19 język konta zapisany do wd.language', () => {
  test.use({ storageState: NO_SESSION, locale: 'en-US' })

  test('konto PL, wd.language=en → po zalogowaniu wd.language=pl, po wylogowaniu login w PL', async ({
    page,
    request,
  }) => {
    await setProfileLanguage(request, await adminToken(request), 'pl')
    // Stary zapis „en” tylko raz (init script biegnie też po reload/nawigacji).
    await page.addInitScript(() => {
      if (sessionStorage.getItem('z219') === null) {
        localStorage.setItem('wd.language', 'en')
        sessionStorage.setItem('z219', '1')
      }
    })
    await page.setViewportSize(DESKTOP)
    await loginViaUi(page)
    await expect(page.getByTestId('home-banner')).toHaveText(/Witaj w Wawelsky Dragon/)
    expect(
      await page.evaluate(() => localStorage.getItem('wd.language')),
      'język konta zapisany do wd.language',
    ).toBe('pl')

    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'Menu użytkownika' }).click()
    await page.getByRole('menuitem', { name: 'Wyloguj' }).click()
    await expect(page).toHaveURL(/\/login/)
    await expect(page.getByTestId('login-submit')).toHaveText('Zaloguj się')
    await page.setViewportSize(MOBILE)
    await page.reload()
    await expect(page.getByTestId('login-submit')).toHaveText('Zaloguj się')
    await shot(page, 'z2-19-login-390')
    await expectNoLayoutDefects(page, 'SC-E67-z2-19 login po wylogowaniu')
  })
})
