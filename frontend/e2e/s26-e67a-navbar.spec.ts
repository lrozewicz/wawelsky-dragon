// Scenariusz SC-E67-05 krok 1 (pasek górny), WP E67-z1a T6: przy 312/320/390 px tytuł „Wawelsky Dragon”
// nie wypycha przycisku motywu i hamburgera poza prawą krawędź okna (QA-UI D1 MAJOR).
import type { Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createDataset } from './helpers'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'

let sessionToken = ''

test.beforeAll(async ({ request }) => {
  await resetDb(request)
  sessionToken = await apiLogin(request)
  await createDataset(request, sessionToken, 'E2E SC-E67-05 pasek')
})

test.afterAll(async ({ request }) => {
  await setProfileLanguage(request, sessionToken, 'pl')
  await resetDb(request)
})

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

const SIZES = [
  { width: 312, height: 675 },
  { width: 320, height: 700 },
  { width: 390, height: 844 },
] as const

for (const size of SIZES) {
  for (const scheme of ['light', 'dark'] as const) {
    test.describe(`pasek górny ${size.width} px ${scheme}`, () => {
      test.use({ viewport: { width: size.width, height: size.height }, colorScheme: scheme })

      test(`SC-E67-05 pasek górny: motyw i hamburger w oknie (${size.width} px, ${scheme})`, async ({
        page,
        request,
      }) => {
        await setProfileLanguage(request, sessionToken, 'pl')
        await openDatasets(page)
        const bar = page.locator('header')
        for (const name of [/tryb kolorów|color mode/i, /otwórz menu|open menu/i]) {
          const button = bar.getByRole('button', { name })
          await expect(button, `przycisk ${String(name)}`).toBeVisible()
          const bb = await button.boundingBox()
          expect(bb, `${String(name)} ma prostokąt`).not.toBeNull()
          expect(bb?.x ?? -1, `${String(name)} od lewej`).toBeGreaterThanOrEqual(0)
          expect((bb?.x ?? 0) + (bb?.width ?? 0), `${String(name)} w oknie`).toBeLessThanOrEqual(
            size.width,
          )
        }
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        )
        expect(overflow, 'brak przewijania poziomego').toBeLessThanOrEqual(0)
        await expectNoLayoutDefects(page, `SC-E67-05 pasek (${size.width}, ${scheme})`)
        if (size.width !== 312) {
          await page.screenshot({ path: `../.task/shots/navbar-${size.width}-${scheme}.png` })
        }
      })
    })
  }
}
