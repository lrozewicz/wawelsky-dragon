// Scenariusz E67-z1a SC-E67-03 (work/wp/E67-z/SCENARIOS.md): błąd serwera (503) na porcji wysyłki
// importu daje stan „wstrzymana” z komunikatem i „Wznów wysyłkę” (nie „Nieznany błąd operacji.”);
// wznowienie kończy się podsumowaniem; zamknięcie dialogu przy wstrzymanej wysyłce kasuje sesję.
// Paczka: mała, poprawna `.wdkb.zip` z helpera (1 porcja) — pierwszy `PUT` dostaje 503 z trasy,
// kolejne przechodzą do prawdziwego API.
import type { Locator, Page, Route } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin } from './helpers'
import { dropFile } from './helpers/dnd'
import { takeOverConsoleGuard } from './helpers/integrations'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { authHeaders, buildWdkbZip } from './helpers/kbTransfer'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const CONTENT_ROUTE = '**/api/wd/v1/dataset-imports/*/content'
const SESSION_RE = /\/api\/wd\/v1\/dataset-imports\/([^/]+)$/

let sessionToken = ''

test.beforeAll(async ({ request }) => {
  await resetDb(request)
  sessionToken = await apiLogin(request)
})

test.afterAll(async ({ request }) => {
  await setProfileLanguage(request, sessionToken, 'pl').catch(() => undefined)
  await resetDb(request)
})

/** Sesja bez formularza logowania (limiter 10/min): `refresh` odpowiada prawdziwym tokenem. */
async function login(page: Page): Promise<void> {
  await page.route('**/api/v1/auth/refresh', (route) =>
    route.fulfill({
      status: 200,
      json: { code: 0, data: { access_token: sessionToken, expires_in: 900 } },
    }),
  )
  await page.goto('/datasets')
}

/** Oczekiwany 503 z mocku trasy porcji — Chromium loguje go jako błąd konsoli. */
function guard503(page: Page): string[] {
  return takeOverConsoleGuard(page, [
    (m) => m.type() === 'error' && m.location().url.includes('/dataset-imports/'),
  ])
}

/** Pierwszy `PUT` porcji -> 503 koperty API, kolejne do prawdziwego API. */
async function failFirstChunk(page: Page): Promise<void> {
  let failed = false
  await page.route(CONTENT_ROUTE, async (route: Route) => {
    if (route.request().method() === 'PUT' && !failed) {
      failed = true
      await route.fulfill({ status: 503, json: { error: { code: 'unavailable', message: 'x' } } })
      return
    }
    await route.continue()
  })
}

/** Dialog importu z upuszczoną paczką; zwraca dialog i `import_id` z odpowiedzi `POST`. */
async function dropPackage(page: Page, importLabel: string, dialogName: string) {
  await page.getByRole('button', { name: importLabel }).click()
  const dialog = page.getByRole('dialog', { name: dialogName })
  await expect(dialog).toBeVisible()
  const created = page.waitForResponse(
    (r) =>
      r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/wd/v1/dataset-imports',
  )
  await dropFile(
    page,
    dialog.getByTestId('kb-import-dropzone'),
    buildWdkbZip({ datasetName: `E2E SC-E67-03 ${Date.now()}` }),
    'paczka.wdkb.zip',
    'application/zip',
  )
  const importId = ((await (await created).json()) as { data: { import_id: string } }).data
    .import_id
  return { dialog, importId }
}

test('SC-E67-03 503 na porcji -> wstrzymana i wznowienie', async ({ page }) => {
  const consoleErrors = guard503(page)
  await failFirstChunk(page)
  await login(page)
  const { dialog } = await dropPackage(page, 'Importuj', 'Importuj bazę wiedzy')

  await expect(
    dialog.getByText('Serwer chwilowo niedostępny (503). Wysyłka wstrzymana.'),
  ).toBeVisible()
  await expect(dialog.getByText('Nieznany błąd operacji.')).toHaveCount(0)
  const resume = dialog.getByRole('button', { name: 'Wznów wysyłkę' })
  await expect(resume).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E67-03 wstrzymana wysyłka (1280)')
  await page.screenshot({ path: '../.task/shots/desktop.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(resume).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E67-03 wstrzymana wysyłka (390)')
  await page.screenshot({ path: '../.task/shots/mobile.png' })

  await resume.click()
  await expect(dialog.getByLabel('Nazwa', { exact: true })).toBeVisible({ timeout: 30_000 })
  expect(consoleErrors, 'poza oczekiwanym 503 brak błędów konsoli').toEqual([])
})

test('SC-E67-03 zamknięcie przy wstrzymanej wysyłce kasuje sesję', async ({ page, request }) => {
  guard503(page)
  await failFirstChunk(page)
  await login(page)
  const { dialog, importId } = await dropPackage(page, 'Importuj', 'Importuj bazę wiedzy')
  await expect(dialog.getByRole('button', { name: 'Wznów wysyłkę' })).toBeVisible()

  const deleted = page.waitForResponse(
    (r) =>
      r.request().method() === 'DELETE' &&
      SESSION_RE.exec(new URL(r.url()).pathname)?.[1] === importId,
  )
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  const response = await deleted
  expect([200, 204], 'DELETE sesji importu').toContain(response.status())

  const after = await request.get(`${API_URL}/api/wd/v1/dataset-imports/${importId}`, {
    headers: authHeaders(sessionToken),
  })
  expect(after.status(), 'GET skasowanej sesji').toBe(404)
})

test('SC-E67-03 EN: komunikat i przycisk po angielsku', async ({ page, request }) => {
  guard503(page)
  await setProfileLanguage(request, sessionToken, 'en')
  await failFirstChunk(page)
  await login(page)
  const { dialog } = await dropPackage(page, 'Import', 'Import knowledge base')
  await expect(
    dialog.getByText('Server temporarily unavailable (503). Upload paused.'),
  ).toBeVisible()
  const resume: Locator = dialog.getByRole('button', { name: 'Resume upload' })
  await expect(resume).toBeVisible()
})
