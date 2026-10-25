// Scenariusze E67-z1a (work/wp/E67-z/SCENARIOS.md): SC-E67-01 — alert sukcesu zielony, ostrzeżenie
// amber, błąd czerwony (jasny/ciemny, 390 px, kontrast >= 4.5:1); SC-E67-02 — „Wyczyść zakończone”
// i auto-ukrycie wiersza zakończonego > 24 h w pasku zadań.
// Sukces: prawdziwy zapis konfiguracji bazy (Alert `datasets.config.saved`). Ostrzeżenie i błąd:
// dialog eksportu z mockiem trasy podglądu K19 (limit przekroczony / HTTP 500). Pasek zadań:
// zasiew `localStorage` `wd.kbTasks.v1:<userId>` (wzór: visual-kb-transfer.spec.ts) + mock tras zadań.
import type { Locator, Page, Route } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createDataset } from './helpers'
import { takeOverConsoleGuard } from './helpers/integrations'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const DATASET_NAME = 'E2E SC-E67 baza paska'

let userId = ''
let sessionToken = ''

test.beforeAll(async ({ request }) => {
  await resetDb(request)
  const token = await apiLogin(request)
  sessionToken = token
  const profile = await request.get(`${API_URL}/api/v1/users/me`, {
    headers: { authorization: `Bearer ${token}` },
  })
  expect(profile.status(), 'GET /api/v1/users/me').toBe(200)
  userId = ((await profile.json()) as { data: { id: string } }).data.id
  await createDataset(request, token, DATASET_NAME)
})

test.afterAll(async ({ request }) => {
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
  await page.goto('/')
  await expect(page.getByTestId('home-banner')).toBeVisible({ timeout: 20_000 })
  // Odczyt koloru po końcu przejść CSS (wzór: s20-input-label-focus).
  await page.addStyleTag({ content: '*{transition:none!important}' })
}

type AlertColors = { r: number; g: number; b: number; ratio: number }

/** Tło alertu (kanały RGB z `getComputedStyle`) i kontrast koloru tekstu względem tła złożonego na tle strony. */
async function alertColors(alert: Locator): Promise<AlertColors> {
  return alert.evaluate((el) => {
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
    const style = getComputedStyle(el)
    // Tło = kolor bazowy + odcień severity w `linear-gradient(tint, tint)` (alert nieprzezroczysty).
    const bg = parse(style.backgroundColor)
    const tint = parse(/rgba?\([^)]+\)/.exec(style.backgroundImage)?.[0] ?? '')
    if (tint.length > 0) {
      const t = tint[3] ?? 1
      for (const i of [0, 1, 2]) bg[i] = (tint[i] ?? 0) * t + (bg[i] ?? 0) * (1 - t)
    }
    // Pierwsze nieprzezroczyste tło przodka (Paper dialogu / tło strony).
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
    const fg = parse(getComputedStyle(el).color)
    const [hi, lo] = [lum(fg), lum(mix)].sort((x, y) => y - x)
    return {
      r: bg[0] ?? 0,
      g: bg[1] ?? 0,
      b: bg[2] ?? 0,
      ratio: ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05),
    }
  })
}

const VARIANTS = [
  { name: 'jasny 1280', scheme: 'light', width: 1280, height: 800 },
  { name: 'ciemny 1280', scheme: 'dark', width: 1280, height: 800 },
  { name: 'jasny 390', scheme: 'light', width: 390, height: 844 },
] as const

for (const variant of VARIANTS) {
  test.describe(`kolory alertów (${variant.name})`, () => {
    test.use({
      viewport: { width: variant.width, height: variant.height },
      colorScheme: variant.scheme,
    })

    test(`SC-E67-01 sukces zapisu konfiguracji jest zielony (${variant.name})`, async ({
      page,
      request,
    }) => {
      const datasetId = await createDataset(
        request,
        sessionToken,
        `E2E SC-E67-01 ${variant.name} ${Date.now()}`,
      )
      await login(page)
      await page.goto(`/dataset/configuration/${datasetId}`)
      await page.getByRole('combobox', { name: 'Metoda chunkowania' }).click()
      await page.getByRole('option', { name: 'Q&A' }).click()
      await page.getByRole('button', { name: 'Zapisz' }).click()
      const apply = page.getByRole('dialog', { name: 'Zastosować zmiany do istniejących plików?' })
      if (await apply.isVisible().catch(() => false)) {
        await apply.getByRole('button', { name: 'Tylko nowe pliki' }).click()
      }
      const alert = page.locator('.MuiAlert-root.MuiAlert-colorSuccess', { hasText: 'Zapisano' })
      await expect(alert).toBeVisible()
      const c = await alertColors(alert)
      expect(c.g, `zielona dominanta tła alertu sukcesu (${JSON.stringify(c)})`).toBeGreaterThan(
        c.r,
      )
      expect(c.g, `zielona dominanta tła alertu sukcesu (${JSON.stringify(c)})`).toBeGreaterThan(
        c.b,
      )
      expect(c.ratio, 'kontrast tekstu alertu sukcesu').toBeGreaterThanOrEqual(4.5)
      await expectNoLayoutDefects(page, `SC-E67-01 alert sukcesu (${variant.name})`)
      await alert.scrollIntoViewIfNeeded()
      await page.screenshot({
        path: `../.task/shots/sc-e67-01-success-${variant.scheme}-${variant.width}.png`,
      })
    })
  })
}

test.describe('ostrzeżenie i błąd', () => {
  const PREVIEW = {
    dataset_id: 'ds-e67',
    name: DATASET_NAME,
    documents: 12,
    chunks: 348,
    estimated_bytes: 25_165_824,
    estimated_bytes_with_vectors: 104_857_600,
    embedding: { model_name: 'BAAI/bge-m3', dimension: 1024 },
    max_bytes: 1_048_576, // mniej niż szacunek -> ostrzeżenie o limicie
  }

  async function openExport(page: Page): Promise<Locator> {
    await login(page)
    await page.goto('/datasets')
    await page.getByRole('button', { name: `Menu bazy wiedzy ${DATASET_NAME}` }).click()
    await page.getByRole('menuitem', { name: 'Eksportuj' }).click()
    const dialog = page.getByRole('dialog', { name: `Eksportuj „${DATASET_NAME}”` })
    await expect(dialog).toBeVisible()
    return dialog
  }

  test('SC-E67-01 ostrzeżenie amber (R>G>B)', async ({ page }) => {
    await page.route('**/api/wd/v1/datasets/*/export/preview', (route: Route) =>
      route.fulfill({ status: 200, json: { data: PREVIEW } }),
    )
    const dialog = await openExport(page)
    const alert = dialog.locator('.MuiAlert-root.MuiAlert-colorWarning')
    await expect(alert).toBeVisible()
    const c = await alertColors(alert)
    expect(c.r, 'amber: R > G').toBeGreaterThan(c.g)
    expect(c.g, 'amber: G > B').toBeGreaterThan(c.b)
    expect(c.ratio, 'kontrast tekstu ostrzeżenia').toBeGreaterThanOrEqual(4.5)
  })

  // Brak naturalnego info w UI zasiewanym tym stosem: sprawdzamy tylko error (czerwony) obok success/warning.
  test('SC-E67-01 błąd czerwony (R>G, R>B)', async ({ page }) => {
    // Oczekiwany HTTP 500 z mocku podglądu Chromium loguje jako błąd konsoli — wąski wyjątek.
    const consoleErrors = takeOverConsoleGuard(page, [
      (m) => m.type() === 'error' && m.location().url.endsWith('/export/preview'),
    ])
    await page.route('**/api/wd/v1/datasets/*/export/preview', (route: Route) =>
      route.fulfill({
        status: 500,
        json: { error: { code: 'internal_error', message: 'boom' } },
      }),
    )
    const dialog = await openExport(page)
    const alert = dialog.locator('.MuiAlert-root.MuiAlert-colorError')
    await expect(alert).toBeVisible()
    const c = await alertColors(alert)
    expect(c.r, 'czerwień: R > G').toBeGreaterThan(c.g)
    expect(c.r, 'czerwień: R > B').toBeGreaterThan(c.b)
    // Amber też ma R > G > B; czerwień od amber odróżnia G ~ B (amber: G wyraźnie nad B).
    expect(Math.abs(c.g - c.b), `czerwień, nie amber (${JSON.stringify(c)})`).toBeLessThanOrEqual(8)
    expect(c.ratio, 'kontrast tekstu błędu').toBeGreaterThanOrEqual(4.5)
    expect(consoleErrors, 'poza oczekiwanym 500 brak błędów konsoli').toEqual([])
  })
})

// --- SC-E67-02 ---------------------------------------------------------------------------

type Row = {
  task_id: string
  kind: 'export' | 'import'
  label: string
  dataset_id: string | null
  added_at: number
  finished_at?: number
  last: Record<string, unknown>
}

function task(
  id: string,
  kind: 'export' | 'import',
  status: 'done' | 'failed' | 'running',
): Record<string, unknown> {
  return {
    task_id: id,
    kind,
    dataset_id: null,
    status,
    stage: status === 'running' ? 'chunks' : null,
    done: status === 'running' ? 10 : 100,
    total: 100,
    progress: status === 'running' ? 0.1 : 1,
    message: status,
    error: status === 'failed' ? { code: 'internal_error', message: 'x' } : null,
    created_at: Date.now(),
    finished_at: null,
    result:
      status !== 'done'
        ? null
        : kind === 'export'
          ? {
              download_url: `/api/wd/v1/exports/${id}/download?sig=x`,
              expires_at: Date.now() + 3_600_000,
              size_bytes: 1_048_576,
              file_name: `${id}.wdkb.zip`,
            }
          : { dataset_id: 'ds-x', dataset_name: 'X', documents: 2, chunks: 20, reembedded: false },
  }
}

function row(id: string, kind: 'export' | 'import', status: 'done' | 'failed' | 'running'): Row {
  return {
    task_id: id,
    kind,
    label: `Baza ${id}`,
    dataset_id: null,
    added_at: Date.now() - 60_000,
    last: task(id, kind, status),
  }
}

/** Zasiew wierszy przed startem aplikacji (init script wykonuje się też po `reload`, więc tylko gdy magazyn pusty). */
async function seed(page: Page, rows: Row[]): Promise<void> {
  await page.addInitScript(
    ({ key, value }) => {
      if (localStorage.getItem(`${key}:seeded`) === null) {
        localStorage.setItem(key, value)
        localStorage.setItem(`${key}:seeded`, '1')
      }
    },
    { key: `wd.kbTasks.v1:${userId}`, value: JSON.stringify(rows) },
  )
  // Trwające zadanie odpytywane co 2 s — odpowiedź zostaje „running”.
  await page.route('**/api/wd/v1/tasks/*', (route: Route) => {
    const id = route.request().url().split('/').pop() ?? ''
    return route.fulfill({ status: 200, json: { data: task(id, 'export', 'running') } })
  })
}

async function openBar(page: Page): Promise<void> {
  await login(page)
  await page.goto('/datasets')
  await expect(page.getByTestId('kb-task-bar')).toBeVisible()
}

test('SC-E67-02 Wyczyść zakończone usuwa zakończone, trwające zostają, po F5 nie wracają', async ({
  page,
}) => {
  await seed(page, [
    row('t-e1', 'export', 'done'),
    row('t-e2', 'export', 'done'),
    row('t-e3', 'export', 'failed'),
    row('t-i1', 'import', 'done'),
    row('t-run', 'export', 'running'),
  ])
  await openBar(page)
  await expect(page.getByTestId('kb-task-row')).toHaveCount(5)
  const clear = page.getByTestId('kb-clear-finished')
  await expect(clear).toBeVisible()
  await expect(clear).toHaveText('Wyczyść zakończone')
  await page.screenshot({ path: '../.task/shots/sc-e67-02-taskbar-1280.png' })
  await clear.click()
  await expect(page.getByTestId('kb-task-row')).toHaveCount(1)
  await expect(page.getByTestId('kb-task-row')).toHaveAttribute('data-task-status', 'running')
  // Gdy 0 zakończonych — przycisk niewidoczny.
  await expect(clear).toBeHidden()
  await page.reload()
  await expect(page.getByTestId('kb-task-bar')).toBeVisible()
  await expect(page.getByTestId('kb-task-row')).toHaveCount(1)
  await expect(page.getByTestId('kb-task-row')).toHaveAttribute('data-task-status', 'running')
  await expect(page.getByTestId('kb-clear-finished')).toBeHidden()
})

test('SC-E67-02 zakończony wiersz starszy niż 24 h znika po F5, młodszy zostaje', async ({
  page,
}) => {
  const now = Date.now()
  const old = { ...row('t-old', 'export', 'done'), finished_at: now - 25 * 3_600_000 }
  const fresh = { ...row('t-new', 'export', 'done'), finished_at: now - 3_600_000 }
  // `added_at` świeży: ukrycie ma wynikać z `finished_at`, nie z wieku wpisu.
  await seed(page, [old, fresh])
  await openBar(page)
  await expect(page.locator('[data-task-id="t-new"]')).toBeVisible()
  await expect(page.locator('[data-task-id="t-old"]')).toHaveCount(0)
  await page.reload()
  await expect(page.locator('[data-task-id="t-new"]')).toBeVisible()
  await expect(page.locator('[data-task-id="t-old"]')).toHaveCount(0)
})

for (const lang of ['pl', 'en'] as const) {
  test.describe(`pasek 390 px (${lang})`, () => {
    test.use({ viewport: { width: 390, height: 844 }, locale: lang === 'en' ? 'en-US' : 'pl-PL' })

    test(`SC-E67-02 przycisk mieści się w pasku (${lang})`, async ({ page, request }) => {
      // Profil nadpisuje locale po zalogowaniu — wariant EN ustawia język profilu (i przywraca PL).
      await setProfileLanguage(request, sessionToken, lang)
      await seed(page, [row('t-a', 'export', 'done'), row('t-b', 'import', 'done')])
      await openBar(page)
      const clear = page.getByTestId('kb-clear-finished')
      await expect(clear).toBeVisible()
      await expect(clear).toHaveText(lang === 'en' ? 'Clear finished' : 'Wyczyść zakończone')
      const box = await clear.boundingBox()
      expect(box, 'przycisk ma wymiary').not.toBeNull()
      expect((box?.x ?? 0) + (box?.width ?? 0), 'przycisk w oknie').toBeLessThanOrEqual(390)
      expect(box?.height ?? 99, 'przycisk w jednej linii').toBeLessThan(40)
      const scrolls = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      )
      expect(scrolls, 'brak poziomego przewijania').toBe(false)
      await expectNoLayoutDefects(page, `SC-E67-02 pasek 390 (${lang})`)
      await page.screenshot({ path: `../.task/shots/sc-e67-02-taskbar-390-${lang}.png` })
      await setProfileLanguage(request, sessionToken, 'pl')
    })
  })
}
