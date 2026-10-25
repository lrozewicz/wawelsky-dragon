// Scenariusz SC-E67-05 (work/wp/E67-z/SCENARIOS.md), WP E67-z1a T4: nagłówek „Bazy wiedzy” bez łamania
// przy 320 px i 390 px z zoomem 125 % (viewport efektywny 312 px), wersja „0.0.0” ukryta w podsumowaniu
// importu, „Kopiuj link” przy odmowie schowka (komunikat + zaznaczone pole z linkiem).
// Podsumowanie importu: prawdziwy backend (upload `buildWdkbZip`), podmiana `summary.wd_version` w odpowiedzi
// GET sesji. Odmowa schowka: wiersz „Gotowe” z zasiewu `localStorage` (wzór: s26-e67a-feedback-taskbar).
import type { Page, Route } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createDataset } from './helpers'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { buildWdkbZip } from './helpers/kbTransfer'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const DATASET_NAME = 'E2E SC-E67-05 baza'
const PACKAGE_NAME = 'E2E SC-E67-05 paczka'

let userId = ''
let sessionToken = ''

test.beforeAll(async ({ request }) => {
  await resetDb(request)
  sessionToken = await apiLogin(request)
  const profile = await request.get(`${API_URL}/api/v1/users/me`, {
    headers: { authorization: `Bearer ${sessionToken}` },
  })
  expect(profile.status(), 'GET /api/v1/users/me').toBe(200)
  userId = ((await profile.json()) as { data: { id: string } }).data.id
  await createDataset(request, sessionToken, DATASET_NAME)
})

test.afterAll(async ({ request }) => {
  await setProfileLanguage(request, sessionToken, 'pl')
  await resetDb(request)
})

/** Sesja bez formularza logowania (limiter 10/min): `refresh` odpowiada prawdziwym tokenem. */
async function openDatasets(page: Page): Promise<void> {
  await page.route('**/api/v1/auth/refresh', (route) =>
    route.fulfill({
      status: 200,
      json: { code: 0, data: { access_token: sessionToken, expires_in: 900 } },
    }),
  )
  await page.goto('/datasets')
  await expect(page.getByTestId('dataset-card').first()).toBeVisible({ timeout: 20_000 })
}

// --- krok 1: nagłówek na wąskim ekranie ----------------------------------------------------------

const NARROW = [
  { name: '320 px', width: 320, height: 700, shot: 'mobile-320.png' },
  { name: '390 px z zoomem 125 % (312 px)', width: 312, height: 675, shot: 'mobile.png' },
] as const

for (const lang of ['pl', 'en'] as const) {
  for (const size of NARROW) {
    test.describe(`nagłówek ${size.name} (${lang})`, () => {
      test.use({
        viewport: { width: size.width, height: size.height },
        locale: lang === 'en' ? 'en-US' : 'pl-PL',
      })

      test(`SC-E67-05 krok 1 tytuł w jednej linii, przyciski bez łamania (${lang}, ${size.name})`, async ({
        page,
        request,
      }) => {
        await setProfileLanguage(request, sessionToken, lang)
        await openDatasets(page)
        const title = page.getByRole('heading', {
          name: lang === 'en' ? 'Datasets' : 'Bazy wiedzy',
        })
        await expect(title).toBeVisible()
        const lineHeight = await title.evaluate((el) => parseFloat(getComputedStyle(el).lineHeight))
        const box = await title.boundingBox()
        expect(box, 'tytuł ma prostokąt').not.toBeNull()
        expect(box?.height ?? 999, 'tytuł w jednej linii').toBeLessThan(lineHeight * 1.6)

        for (const name of lang === 'en'
          ? ['Import', 'Create dataset']
          : ['Importuj', 'Utwórz dataset']) {
          const button = page.getByRole('button', { name, exact: true })
          await expect(button, `przycisk „${name}”`).toBeVisible()
          const bb = await button.boundingBox()
          expect(bb?.height ?? 999, `„${name}” bez łamania tekstu`).toBeLessThanOrEqual(48)
          expect(
            (bb?.x ?? -1) >= 0 && (bb?.x ?? 0) + (bb?.width ?? 0) <= size.width,
            `„${name}” w oknie`,
          ).toBe(true)
        }

        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        )
        expect(overflow, 'brak przewijania poziomego').toBeLessThanOrEqual(0)
        await expectNoLayoutDefects(page, `SC-E67-05 krok 1 (${lang}, ${size.name})`)
        if (lang === 'pl') await page.screenshot({ path: `../.task/shots/${size.shot}` })
      })
    })
  }
}

test('SC-E67-05 krok 1 desktop 1280 px', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await setProfileLanguage(page.request, sessionToken, 'pl')
  await openDatasets(page)
  await expect(page.getByRole('button', { name: 'Utwórz dataset', exact: true })).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E67-05 desktop')
  await page.screenshot({ path: '../.task/shots/desktop.png' })
})

// --- krok 2: wersja źródła w podsumowaniu importu -----------------------------------------------

/** Wgrywa paczkę w dialogu importu; odpowiedź sesji (porcja `content` albo GET) dostaje podmienioną `summary.wd_version`. */
async function summaryLine(page: Page, wdVersion: string): Promise<string> {
  await page.route('**/api/wd/v1/dataset-imports/**', async (route: Route) => {
    if (['DELETE', 'POST'].includes(route.request().method())) return route.fallback()
    const response = await route.fetch()
    const body = (await response.json()) as { data?: { summary?: { wd_version: string } | null } }
    if (body.data?.summary) body.data.summary.wd_version = wdVersion
    return route.fulfill({ response, json: body })
  })
  await openDatasets(page)
  await page.getByRole('button', { name: 'Importuj', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
  await dialog.locator('input[type="file"]').setInputFiles({
    name: 'paczka.wdkb.zip',
    mimeType: 'application/zip',
    buffer: buildWdkbZip({ datasetName: PACKAGE_NAME }),
  })
  const line = dialog.getByText(/utworzona .* w Wawelsky Dragon/)
  await expect(line).toBeVisible({ timeout: 60_000 })
  return (await line.textContent()) ?? ''
}

test('SC-E67-05 krok 2 wersja 0.0.0 w podsumowaniu importu jest ukryta', async ({ page }) => {
  const text = await summaryLine(page, '0.0.0')
  expect(text).not.toContain('0.0.0')
  await expectNoLayoutDefects(page, 'SC-E67-05 krok 2 — podsumowanie importu')
})

test('SC-E67-05 krok 2 realna wersja źródła jest pokazana', async ({ page }) => {
  const text = await summaryLine(page, '1.4.2')
  expect(text).toContain('1.4.2')
})

// --- krok 3: „Kopiuj link” przy odmowie schowka -------------------------------------------------

test.describe('odmowa schowka', () => {
  test.use({ permissions: [] })

  test('SC-E67-05 krok 3 komunikat i zaznaczone pole z linkiem', async ({ page }) => {
    const id = 't-copy'
    const result = {
      download_url: `/api/wd/v1/exports/${id}/download?sig=x`,
      expires_at: Date.now() + 3_600_000,
      size_bytes: 1_048_576,
      file_name: `${id}.wdkb.zip`,
    }
    const last = {
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
      created_at: Date.now(),
      finished_at: null,
      result,
    }
    await page.addInitScript(({ key, value }) => localStorage.setItem(key, value), {
      key: `wd.kbTasks.v1:${userId}`,
      value: JSON.stringify([
        {
          task_id: id,
          kind: 'export',
          label: DATASET_NAME,
          dataset_id: null,
          added_at: Date.now() - 60_000,
          last,
        },
      ]),
    })
    // Schowek odmawia: brak `navigator.clipboard` i `execCommand('copy')` → false.
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
      document.execCommand = (() => false) as typeof document.execCommand
    })
    await page.route('**/api/wd/v1/tasks/*', (route: Route) =>
      route.fulfill({ status: 200, json: { data: last } }),
    )
    await openDatasets(page)
    await page.getByRole('button', { name: 'Kopiuj link', exact: true }).click()

    await expect(
      page.getByRole('alert').filter({ hasText: 'Nie udało się skopiować — zaznacz link ręcznie' }),
    ).toBeVisible()
    const field = page.getByTestId('kb-copy-link-field').locator('input')
    const value = await field.inputValue()
    expect(value).toContain('/api/wd/')
    expect(value).toContain('download')
    await expect(field).toHaveAttribute('readonly', '')
    expect(await page.evaluate(() => document.getSelection()?.toString() ?? '')).toBe(value)
    await expectNoLayoutDefects(page, 'SC-E67-05 krok 3 — pole z linkiem')
    await page.screenshot({ path: '../.task/shots/copy-link-fallback.png' })
  })
})
