// Scenariusze E67-z2 (work/wp/E67-z2/SCENARIOS.md) SC-E67-z2-08…11 — wizualne MINOR-y eksportu/importu:
// -08 lista eksportów (wiersze tej samej bazy odróżnialne datą/godziną, „Pobierz”/„Kopiuj link” to
// przyciski), -09 ostrzeżenie „Nazwa zajęta” znika przy zaproponowanej wolnej nazwie, -10 ciemny motyw:
// toast sukcesu i wiersz „Gotowe” zielone z kontrastem >= 4,5:1, -11 menuitem „Eksportuj” ma nazwę.
// Wiersze paska: zasiew `localStorage` `wd.kbTasks.v1:<userId>` (wzór: s26-e67a-feedback-taskbar);
// import: prawdziwy backend (baza o nazwie z paczki istnieje -> `name_taken`).
import type { Locator, Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createDataset } from './helpers'
import { dropFile } from './helpers/dnd'
import { buildWdkbZip } from './helpers/kbTransfer'
import { expectNoLayoutDefects } from './helpers/layout'

const DATASET_NAME = 'E2E SC-E67-z2 baza eksportów'

let userId = ''
let sessionToken = ''

test.beforeAll(async ({ request }) => {
  await resetDb(request)
  sessionToken = await apiLogin(request)
  const profile = await request.get(`${process.env.WD_E2E_API_URL ?? ''}/api/v1/users/me`, {
    headers: { authorization: `Bearer ${sessionToken}` },
  })
  expect(profile.status(), 'GET /api/v1/users/me').toBe(200)
  userId = ((await profile.json()) as { data: { id: string } }).data.id
})

test.afterAll(async ({ request }) => {
  await resetDb(request)
})

/** Sesja bez formularza logowania (limiter 10/min): `refresh` odpowiada prawdziwym tokenem. */
async function login(page: Page, path = '/datasets'): Promise<void> {
  await page.route('**/api/v1/auth/refresh', (route) =>
    route.fulfill({
      status: 200,
      json: { code: 0, data: { access_token: sessionToken, expires_in: 900 } },
    }),
  )
  await page.goto(path)
  // Odczyt koloru po końcu przejść CSS (wzór: s20-input-label-focus).
  await page.addStyleTag({ content: '*{transition:none!important}' })
}

type StoredRow = {
  task_id: string
  kind: 'export'
  label: string
  dataset_id: string | null
  added_at: number
  last: Record<string, unknown>
}

/** Wiersz zakończonego eksportu utworzony `createdAt` (ms). */
function exportRow(id: string, createdAt: number): StoredRow {
  return {
    task_id: id,
    kind: 'export',
    label: DATASET_NAME,
    dataset_id: null,
    added_at: createdAt,
    last: {
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
      finished_at: createdAt + 30_000,
      result: {
        download_url: `/api/wd/v1/exports/${id}/download?sig=x`,
        expires_at: Date.now() + 3_600_000,
        size_bytes: 1_048_576,
        file_name: `${id}.wdkb.zip`,
      },
    },
  }
}

async function seedRows(page: Page, rows: StoredRow[]): Promise<void> {
  await page.addInitScript(
    ({ key, value }) => {
      if (localStorage.getItem(`${key}:seeded`) === null) {
        localStorage.setItem(key, value)
        localStorage.setItem(`${key}:seeded`, '1')
      }
    },
    { key: `wd.kbTasks.v1:${userId}`, value: JSON.stringify(rows) },
  )
}

type Contrast = { r: number; g: number; b: number; ratio: number }

/**
 * Efektywne tło elementu (warstwy `background-color` + gradient-odcień od elementu w górę do
 * pierwszego nieprzezroczystego przodka) i kontrast koloru tekstu elementu względem niego.
 */
async function textContrast(target: Locator): Promise<Contrast> {
  return target.evaluate((el) => {
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
    // Warstwy od elementu w górę; zatrzymanie na pierwszej nieprzezroczystej.
    const layers: number[][] = []
    for (let node: Element | null = el; node !== null; node = node.parentElement) {
      const style = getComputedStyle(node)
      const tint = /rgba?\([^)]+\)/.exec(style.backgroundImage)?.[0]
      if (tint !== undefined) layers.push(parse(tint))
      const color = parse(style.backgroundColor)
      layers.push(color)
      if ((color[3] ?? 1) >= 1) break
    }
    let mix = [255, 255, 255]
    for (const layer of layers.reverse()) {
      const a = layer[3] ?? 1
      mix = [0, 1, 2].map((i) => (layer[i] ?? 0) * a + (mix[i] ?? 0) * (1 - a))
    }
    const [hi, lo] = [lum(parse(getComputedStyle(el).color)), lum(mix)].sort((x, y) => y - x)
    return {
      r: mix[0] ?? 0,
      g: mix[1] ?? 0,
      b: mix[2] ?? 0,
      ratio: ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05),
    }
  })
}

const VIEWPORTS = [
  { name: '1280', width: 1280, height: 800 },
  { name: '390', width: 390, height: 844 },
] as const

for (const vp of VIEWPORTS) {
  test.describe(`E67-z2 ${vp.name}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } })

    test(`SC-E67-z2-08 wiersze eksportów tej samej bazy są odróżnialne (${vp.name})`, async ({
      page,
    }) => {
      const now = Date.now()
      await seedRows(page, [
        exportRow('t-z2-a', now - 3 * 3_600_000),
        exportRow('t-z2-b', now - 60_000),
      ])
      await login(page)
      const rows = page.getByTestId('kb-task-row')
      await expect(rows).toHaveCount(2)
      const texts = await rows.allInnerTexts()
      expect(new Set(texts).size, `różny tekst wierszy: ${JSON.stringify(texts)}`).toBe(2)
      for (const row of await rows.all()) {
        await expect(row.getByRole('button', { name: 'Pobierz' })).toBeVisible()
        await expect(row.getByRole('button', { name: 'Kopiuj link' })).toBeVisible()
        // Przyciski z obrysem — nie wyglądają jak zwykły tekst.
        for (const name of ['Pobierz', 'Kopiuj link']) {
          const width = await row
            .getByRole('button', { name })
            .evaluate((el) => parseFloat(getComputedStyle(el).borderTopWidth))
          expect(width, `obrys przycisku „${name}”`).toBeGreaterThan(0)
        }
      }
      await expectNoLayoutDefects(page, `SC-E67-z2-08 lista eksportów (${vp.name})`)
      await page.screenshot({ path: `../.task/shots/sc-08-${vp.name}.png` })
    })

    test(`SC-E67-z2-09 ostrzeżenie „Nazwa zajęta” znika przy wolnej nazwie (${vp.name})`, async ({
      page,
      request,
    }) => {
      const taken = `E2E SC-E67-z2-09 ${vp.name} ${Date.now()}`
      await createDataset(request, sessionToken, taken)
      await login(page)
      await page.getByRole('button', { name: 'Importuj' }).click()
      const dialog = page.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
      await expect(dialog).toBeVisible()
      await dropFile(
        page,
        dialog.getByTestId('kb-import-dropzone'),
        buildWdkbZip({ datasetName: taken }),
        'paczka.wdkb.zip',
        'application/zip',
      )
      const nameField = dialog.getByLabel('Nazwa', { exact: true })
      await expect(nameField).toBeVisible({ timeout: 30_000 })
      // Dialog proponuje wolną nazwę (różną od zajętej) — ostrzeżenie nie ma sensu.
      await expect(nameField).not.toHaveValue(taken)
      const warning = dialog.getByTestId('kb-import-name-taken')
      await expect(warning).toHaveCount(0)
      await expectNoLayoutDefects(page, `SC-E67-z2-09 wolna nazwa (${vp.name})`)
      await page.screenshot({ path: `../.task/shots/sc-09-free-${vp.name}.png` })

      await nameField.fill(taken)
      await expect(warning).toBeVisible()
      await nameField.fill(`${taken} (2)`)
      await expect(warning).toHaveCount(0)
    })

    test(`SC-E67-z2-11 menuitem „Eksportuj” ma nazwę dostępnościową (${vp.name})`, async ({
      page,
      request,
    }) => {
      const name = `E2E SC-E67-z2-11 ${vp.name} ${Date.now()}`
      await createDataset(request, sessionToken, name)
      await login(page)
      await page.getByRole('button', { name: `Menu bazy wiedzy ${name}` }).click()
      const item = page.getByRole('menuitem', { name: /Eksportuj/ })
      await expect(item).toBeVisible()
      await expectNoLayoutDefects(page, `SC-E67-z2-11 menu karty (${vp.name})`)
      await page.screenshot({ path: `../.task/shots/sc-11-${vp.name}.png` })
    })
  })

  test.describe(`E67-z2 ciemny ${vp.name}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height }, colorScheme: 'dark' })

    test(`SC-E67-z2-10 toast sukcesu i wiersz „Gotowe” zielone w ciemnym motywie (${vp.name})`, async ({
      page,
      request,
    }) => {
      const datasetId = await createDataset(
        request,
        sessionToken,
        `E2E SC-E67-z2-10 ${vp.name} ${Date.now()}`,
      )
      await seedRows(page, [exportRow('t-z2-10', Date.now() - 60_000)])
      await login(page, `/dataset/configuration/${datasetId}`)
      await page.getByRole('combobox', { name: 'Metoda chunkowania' }).click()
      await page.getByRole('option', { name: 'Q&A' }).click()
      await page.getByRole('button', { name: 'Zapisz' }).click()
      const apply = page.getByRole('dialog', { name: 'Zastosować zmiany do istniejących plików?' })
      if (await apply.isVisible().catch(() => false)) {
        await apply.getByRole('button', { name: 'Tylko nowe pliki' }).click()
      }
      const toast = page.locator('.MuiAlert-root.MuiAlert-colorSuccess', { hasText: 'Zapisano' })
      await expect(toast).toBeVisible()
      const text = toast.locator('.MuiAlert-message')
      const t = await textContrast(text)
      expect(
        Math.min(t.g - t.r, t.g - t.b),
        `zielone tło toastu (${JSON.stringify(t)})`,
      ).toBeGreaterThanOrEqual(15)
      expect(t.ratio, `kontrast tekstu toastu (${JSON.stringify(t)})`).toBeGreaterThanOrEqual(4.5)
      await page.screenshot({ path: `../.task/shots/sc-10-toast-dark-${vp.name}.png` })

      await page.goto('/datasets')
      const rowText = page.getByTestId('kb-task-row').getByText(/^Gotowe/)
      await expect(rowText).toBeVisible()
      const r = await textContrast(rowText)
      expect(
        Math.min(r.g - r.r, r.g - r.b),
        `zielone tło wiersza (${JSON.stringify(r)})`,
      ).toBeGreaterThanOrEqual(15)
      expect(r.ratio, `kontrast tekstu wiersza (${JSON.stringify(r)})`).toBeGreaterThanOrEqual(4.5)
      await expectNoLayoutDefects(page, `SC-E67-z2-10 wiersz Gotowe ciemny (${vp.name})`)
      await page.screenshot({ path: `../.task/shots/sc-10-row-dark-${vp.name}.png` })
    })
  })
}
