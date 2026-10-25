// Poprawki po QA-UI E67-z1a-1 (T7): D2 pasek błędnego uploadu, D5 stopka i przycisk w uploadzie (390 px),
// D3 potwierdzenie „Zapisano” widoczne w oknie, D4 kolor wiersza „Gotowe”/„Błąd” w pasku zadań,
// pauza importu jako ostrzeżenie (amber). Tytuły testów zaczynają się od „QA-Dn”, żeby wołać je przez `-g`.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import type { Locator, Page, Route } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createDataset, seedCorpus } from './helpers'
import { dropFile } from './helpers/dnd'
import { takeOverConsoleGuard } from './helpers/integrations'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { buildWdkbZip } from './helpers/kbTransfer'

const API_URL = process.env.WD_E2E_API_URL ?? ''

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
})

test.afterAll(async ({ request }) => {
  await setProfileLanguage(request, sessionToken, 'pl').catch(() => undefined)
  await resetDb(request)
})

/** Sesja bez formularza logowania (limiter 10/min): `refresh` odpowiada prawdziwym tokenem. */
async function login(page: Page, path = '/'): Promise<void> {
  await page.route('**/api/v1/auth/refresh', (route) =>
    route.fulfill({
      status: 200,
      json: { code: 0, data: { access_token: sessionToken, expires_in: 900 } },
    }),
  )
  await page.goto(path)
  await expect(page.locator('main, [data-testid="home-banner"]').first()).toBeVisible({
    timeout: 20_000,
  })
  // Odczyt koloru po końcu przejść CSS (wzór: s26-e67a-feedback-taskbar).
  await page.addStyleTag({ content: '*{transition:none!important}' })
}

type Colors = { r: number; g: number; b: number; ratio: number }

/** Tło elementu (RGB złożone na tle przodka) i kontrast koloru tekstu (`textSelector` albo sam element). */
async function colorsOf(element: Locator, textSelector?: string): Promise<Colors> {
  return element.evaluate((el, selector) => {
    const parse = (value: string): number[] =>
      (/rgba?\(([^)]+)\)/.exec(value)?.[1] ?? '0,0,0,0')
        .split(/[,\s/]+/)
        .filter(Boolean)
        .map(Number)
    const lin = (c: number): number => {
      const s = c / 255
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
    }
    const lum = (c: number[]): number =>
      0.2126 * lin(c[0] ?? 0) + 0.7152 * lin(c[1] ?? 0) + 0.0722 * lin(c[2] ?? 0)
    const bg = parse(getComputedStyle(el).backgroundColor)
    let base = [255, 255, 255]
    for (let node = el.parentElement; node !== null; node = node.parentElement) {
      const c = parse(getComputedStyle(node).backgroundColor)
      if ((c[3] ?? 1) >= 1) {
        base = c
        break
      }
    }
    const a = bg[3] ?? 1
    const mix = [0, 1, 2].map((i) => (bg[i] ?? 0) * a + (base[i] ?? 0) * (1 - a))
    const textEl = selector === undefined ? el : (el.querySelector(selector) ?? el)
    const fg = parse(getComputedStyle(textEl).color)
    const [hi, lo] = [lum(fg), lum(mix)].sort((x, y) => y - x)
    return {
      r: mix[0] ?? 0,
      g: mix[1] ?? 0,
      b: mix[2] ?? 0,
      ratio: ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05),
    }
  }, textSelector)
}

// --- D2 / D5: dialog uploadu -------------------------------------------------------------

const REJECTED = { name: 'sample.pdf', mime: 'application/pdf' }
const ACCEPTED = {
  name: 'sample.xlsx',
  mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

function fixtureBytes(name: string): Buffer {
  return readFileSync(fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url)))
}

/** Dialog uploadu z dwoma plikami (REJECTED, ACCEPTED); serwer odrzuca REJECTED kodem `status`. */
async function uploadWithRejection(page: Page, status: number): Promise<Locator> {
  const datasetId = await createDataset(
    page.context().request,
    sessionToken,
    `E2E QA upload ${String(status)} ${Date.now()}`,
  )
  await login(page, `/dataset/files/${datasetId}`)
  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByTestId('upload-parse-toggle').uncheck()
  for (const file of [REJECTED, ACCEPTED]) {
    await dropFile(
      page,
      dialog.getByTestId('upload-dropzone'),
      fixtureBytes(file.name),
      file.name,
      file.mime,
    )
    await expect(dialog.getByText(file.name, { exact: true })).toBeVisible()
  }
  await page.route('**/api/v1/datasets/*/documents', async (route: Route) => {
    const body = route.request().postDataBuffer()?.toString('latin1') ?? ''
    if (route.request().method() === 'POST' && body.includes(`filename="${REJECTED.name}"`)) {
      await route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify({ code: 101, message: 'Plik odrzucony', data: false }),
      })
      return
    }
    await route.fallback()
  })
  await dialog.getByTestId('upload-start').click()
  await expect(dialog.getByTestId('upload-summary')).toHaveText(/1 (z|of) 2/, { timeout: 60_000 })
  return dialog
}

for (const status of [400, 500]) {
  test(`QA-D2 pasek odrzuconego pliku jest czerwony (HTTP ${String(status)})`, async ({ page }) => {
    takeOverConsoleGuard(page, [(m) => m.type() === 'error' && m.text().includes(String(status))])
    const dialog = await uploadWithRejection(page, status)
    const failed = dialog.getByTestId('upload-progress-0')
    const done = dialog.getByTestId('upload-progress-1')
    await expect(failed).toHaveClass(/MuiLinearProgress-colorError/)
    await expect(failed).toHaveAttribute('aria-valuenow', '100')
    await expect(done).not.toHaveClass(/MuiLinearProgress-colorError/)
    await expect(done).toHaveAttribute('aria-valuenow', '100')
  })
}

test.describe('QA-D5 upload 390 px EN', () => {
  test.use({ viewport: { width: 390, height: 844 }, locale: 'en-US' })

  test('QA-D5 stopka wyrównana do listy, przycisk wyboru plików w jednej linii', async ({
    page,
    request,
  }) => {
    takeOverConsoleGuard(page, [(m) => m.type() === 'error' && m.text().includes('400')])
    await setProfileLanguage(request, sessionToken, 'en')
    const dialog = await uploadWithRejection(page, 400)
    const choose = dialog.getByRole('button', { name: 'Choose files' })
    const chooseBox = await choose.boundingBox()
    expect(chooseBox?.height ?? 99, 'wysokość przycisku „Choose files”').toBeLessThanOrEqual(48)
    // Przycisk ma min-height 40 px, więc dwie linie tekstu mieszczą się w „≤ 48” — liczymy linie tekstu.
    const lines = await choose.evaluate((el) => {
      const text = Array.from(el.childNodes).find((node) => node.nodeType === Node.TEXT_NODE)
      const range = document.createRange()
      if (text !== undefined) range.selectNodeContents(text)
      return range.getClientRects().length
    })
    expect(lines, 'etykieta „Choose files” w jednej linii').toBe(1)
    const summary = await dialog.getByTestId('upload-summary').boundingBox()
    const list = await dialog.getByText(ACCEPTED.name, { exact: true }).boundingBox()
    expect(
      Math.abs((summary?.x ?? -99) - (list?.x ?? 99)),
      `stopka ${String(summary?.x)} vs lista ${String(list?.x)}`,
    ).toBeLessThanOrEqual(1)
    await expectNoLayoutDefects(page, 'QA-D5 dialog uploadu 390')
    await page.screenshot({ path: '../.task/shots/mobile.png' })
    await setProfileLanguage(request, sessionToken, 'pl')
  })
})

// --- D3: potwierdzenie zapisu konfiguracji w oknie ----------------------------------------

for (const size of [
  { name: '1280x720', width: 1280, height: 720 },
  { name: '390x844', width: 390, height: 844 },
]) {
  test(`QA-D3 „Zapisano” widoczne w oknie bez przewijania (${size.name})`, async ({
    page,
    request,
  }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: size.width, height: size.height })
    const corpus = await seedCorpus(request, sessionToken, {
      datasetName: `E2E QA-D3 ${size.name} ${Date.now()}`,
      documentName: 'qa-d3.txt',
      documentBody: 'Smok wawelski mieszka pod Wawelem.',
    })
    await login(page, `/dataset/configuration/${corpus.datasetId}`)
    await page.getByRole('combobox', { name: 'Metoda chunkowania' }).click()
    await page.getByRole('option', { name: 'Q&A' }).click()
    await page.getByRole('button', { name: 'Zapisz' }).click()
    const alert = page.locator('.MuiAlert-root.MuiAlert-colorSuccess', { hasText: 'Zapisano' })
    await expect(alert).toBeVisible()
    await expect(alert).toBeInViewport({ timeout: 2_000 })
    const c = await colorsOf(alert)
    expect(c.g, `zielone tło potwierdzenia (${JSON.stringify(c)})`).toBeGreaterThan(c.r)
    expect(c.g, `zielone tło potwierdzenia (${JSON.stringify(c)})`).toBeGreaterThan(c.b)
    if (size.width === 1280) await page.screenshot({ path: '../.task/shots/desktop.png' })
    const apply = page.getByRole('dialog', { name: 'Zastosować zmiany do istniejących plików?' })
    if (await apply.isVisible().catch(() => false)) {
      await apply.getByRole('button', { name: 'Tylko nowe pliki' }).click()
    }
  })
}

// --- D4: kolor wiersza paska zadań --------------------------------------------------------

type TaskStatus = 'done' | 'failed'

function seedRow(id: string, status: TaskStatus): Record<string, unknown> {
  return {
    task_id: id,
    kind: 'export',
    label: `Baza ${id}`,
    dataset_id: null,
    added_at: Date.now() - 60_000,
    last: {
      task_id: id,
      kind: 'export',
      dataset_id: null,
      status,
      stage: null,
      done: 100,
      total: 100,
      progress: 1,
      message: status,
      error: status === 'failed' ? { code: 'internal_error', message: 'x' } : null,
      created_at: Date.now(),
      finished_at: null,
      result:
        status === 'done'
          ? {
              download_url: `/api/wd/v1/exports/${id}/download?sig=x`,
              expires_at: Date.now() + 3_600_000,
              size_bytes: 1_048_576,
              file_name: `${id}.wdkb.zip`,
            }
          : null,
    },
  }
}

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`QA-D4 pasek zadań (${scheme})`, () => {
    test.use({ colorScheme: scheme })

    test(`QA-D4 wiersz „Gotowe” zielony, „Błąd” czerwony (${scheme})`, async ({ page }) => {
      await page.addInitScript(
        ({ key, value }) => {
          if (localStorage.getItem(`${key}:seeded`) === null) {
            localStorage.setItem(key, value)
            localStorage.setItem(`${key}:seeded`, '1')
          }
        },
        {
          key: `wd.kbTasks.v1:${userId}`,
          value: JSON.stringify([seedRow('t-ok', 'done'), seedRow('t-bad', 'failed')]),
        },
      )
      await login(page, '/datasets')
      await expect(page.getByTestId('kb-task-bar')).toBeVisible()
      const done = page.locator('[data-task-status="done"]')
      const failed = page.locator('[data-task-status="failed"]')
      await expect(done).toBeVisible()
      const d = await colorsOf(done, 'p')
      expect(d.g, `done: G > R (${JSON.stringify(d)})`).toBeGreaterThan(d.r)
      expect(d.g, `done: G > B (${JSON.stringify(d)})`).toBeGreaterThan(d.b)
      expect(d.ratio, 'kontrast tekstu wiersza „Gotowe”').toBeGreaterThanOrEqual(4.5)
      const f = await colorsOf(failed, 'p')
      expect(f.r, `failed: R > G (${JSON.stringify(f)})`).toBeGreaterThan(f.g)
      expect(f.r, `failed: R > B (${JSON.stringify(f)})`).toBeGreaterThan(f.b)
      expect(f.ratio, 'kontrast tekstu wiersza „Błąd”').toBeGreaterThanOrEqual(4.5)
      await page.screenshot({ path: `../.task/shots/taskbar-${scheme}.png` })
    })
  })
}

// --- Pauza importu jako ostrzeżenie -------------------------------------------------------

test('QA-pauza komunikat wstrzymania importu jest amber', async ({ page }) => {
  takeOverConsoleGuard(page, [
    (m) => m.type() === 'error' && m.location().url.includes('/dataset-imports/'),
  ])
  let failed = false
  await page.route('**/api/wd/v1/dataset-imports/*/content', async (route: Route) => {
    if (route.request().method() === 'PUT' && !failed) {
      failed = true
      await route.fulfill({ status: 503, json: { error: { code: 'unavailable', message: 'x' } } })
      return
    }
    await route.continue()
  })
  await login(page, '/datasets')
  await page.getByRole('button', { name: 'Importuj' }).click()
  const dialog = page.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
  await expect(dialog).toBeVisible()
  await dropFile(
    page,
    dialog.getByTestId('kb-import-dropzone'),
    buildWdkbZip({ datasetName: `E2E QA-pauza ${Date.now()}` }),
    'paczka.wdkb.zip',
    'application/zip',
  )
  const alert = dialog.getByRole('alert').filter({
    hasText: 'Serwer chwilowo niedostępny (503). Wysyłka wstrzymana.',
  })
  await expect(alert).toBeVisible()
  await expect(alert).toHaveClass(/MuiAlert-colorWarning/)
  const c = await colorsOf(alert)
  expect(c.r, `amber: R > G (${JSON.stringify(c)})`).toBeGreaterThan(c.g)
  expect(c.g, `amber: G > B (${JSON.stringify(c)})`).toBeGreaterThan(c.b)
  expect(c.ratio, 'kontrast tekstu ostrzeżenia').toBeGreaterThanOrEqual(4.5)
  await page.screenshot({ path: '../.task/shots/import-pause.png' })
})
