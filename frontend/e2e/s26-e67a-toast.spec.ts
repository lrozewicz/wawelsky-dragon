// SC-E67-01 (QA-UI E67-z1a-2, D6): toast „Zapisano” jest nieprzezroczysty i nie zasłania sidebara
// (md+) ani przycisku „Zapisz” (poniżej md), w ciemnym i jasnym motywie, z kontrastem >= 4.5:1.
import type { Locator, Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, seedCorpus } from './helpers'

let sessionToken = ''

test.beforeAll(async ({ request }) => {
  await resetDb(request)
  sessionToken = await apiLogin(request)
})

test.afterAll(async ({ request }) => {
  await resetDb(request)
})

type Box = { x: number; y: number; width: number; height: number }

function intersects(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
}

/** Alfa tła i kontrast tekstu do tła toastu (tło ma być nieprzezroczyste, więc bez mieszania). */
async function alertColors(alert: Locator): Promise<{ alpha: number; ratio: number }> {
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
    const bg = parse(style.backgroundColor)
    // Odcień severity w `linear-gradient(tint, tint)` składamy na nieprzezroczyste tło bazowe.
    const tint = parse(/rgba?\([^)]+\)/.exec(style.backgroundImage)?.[0] ?? '')
    const alpha = bg[3] ?? 1
    if (tint.length > 0) {
      const t = tint[3] ?? 1
      for (const i of [0, 1, 2]) bg[i] = (tint[i] ?? 0) * t + (bg[i] ?? 0) * (1 - t)
    }
    const fg = parse(getComputedStyle(el.querySelector('.MuiAlert-message') ?? el).color)
    const [hi, lo] = [lum(fg), lum(bg)].sort((x, y) => y - x)
    return { alpha, ratio: ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05) }
  })
}

async function box(locator: Locator, what: string): Promise<Box> {
  const b = await locator.boundingBox()
  expect(b, what).not.toBeNull()
  return b as Box
}

async function saveConfig(page: Page, datasetId: string): Promise<Locator> {
  await page.route('**/api/v1/auth/refresh', (route) =>
    route.fulfill({
      status: 200,
      json: { code: 0, data: { access_token: sessionToken, expires_in: 900 } },
    }),
  )
  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.locator('main').first()).toBeVisible({ timeout: 20_000 })
  await page.addStyleTag({ content: '*{transition:none!important}' })
  await page.getByRole('combobox', { name: 'Metoda chunkowania' }).click()
  await page.getByRole('option', { name: 'Q&A' }).click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  // Dataset z plikami: najpierw dialog „Zastosować zmiany…”, „Zapisano” pojawia się po wyborze.
  await page
    .getByRole('dialog', { name: 'Zastosować zmiany do istniejących plików?' })
    .getByRole('button', { name: 'Tylko nowe pliki' })
    .click()
  const alert = page.getByRole('alert').filter({ hasText: 'Zapisano' })
  await expect(alert).toBeVisible()
  return alert
}

for (const scheme of ['dark', 'light'] as const) {
  for (const size of [
    { name: '1280', width: 1280, height: 800 },
    { name: '390', width: 390, height: 844 },
  ]) {
    test(`SC-E67-01 toast Zapisano: nieprzezroczysty i poza sidebarem (${scheme} ${size.name})`, async ({
      page,
      request,
    }) => {
      test.setTimeout(180_000)
      await page.emulateMedia({ colorScheme: scheme })
      await page.setViewportSize({ width: size.width, height: size.height })
      const corpus = await seedCorpus(request, sessionToken, {
        datasetName: `E2E SC-E67-01 ${scheme} ${size.name} ${Date.now()}`,
        documentName: 'sc-e67-01.txt',
        documentBody: 'Smok wawelski mieszka pod Wawelem.',
      })
      const alert = await saveConfig(page, corpus.datasetId)

      const colors = await alertColors(alert)
      expect(colors.alpha, 'tło toastu nieprzezroczyste').toBe(1)
      expect(colors.ratio, 'kontrast tekstu toastu').toBeGreaterThanOrEqual(4.5)

      const toast = await box(alert, 'toast')
      if (size.width >= 900) {
        const sidebar = await box(page.locator('.MuiDrawer-paper').first(), 'sidebar')
        expect(
          intersects(toast, sidebar),
          `toast ${JSON.stringify(toast)} nie zasłania sidebara`,
        ).toBe(false)
      } else {
        const save = await box(page.getByRole('button', { name: 'Zapisz' }), 'przycisk Zapisz')
        expect(intersects(toast, save), `toast ${JSON.stringify(toast)} nie zasłania Zapisz`).toBe(
          false,
        )
      }
      await page.screenshot({
        path: `../.task/shots/${size.width === 1280 ? 'desktop' : 'mobile'}${scheme === 'dark' ? '' : '-light'}.png`,
      })
    })
  }
}
