// Scenariusz S6-16d (rozszerzenie WP E5-H6a §C2): karta zbioru na liście „Bazy wiedzy" i
// mini-karta na Home nawigują routerem (SPA) BEZ przeładowania dokumentu, a semantyka linku
// zostaje. Dowód braku przeładowania: znacznik `window.__marker` ustawiony przed klikiem przeżywa
// nawigację wyłącznie wtedy, gdy dokument NIE został przeładowany (na kodzie sprzed poprawki,
// gdzie karta była zwykłym `<a href>`, po pełnym przeładowaniu był `undefined`).
import type { Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createDataset, loginViaUi } from './helpers'
import { deleteDataset } from './helpers/files'

const DATASET_NAME = 'E2E S6-16d nawigacja'

/** Ustawia znacznik przeładowania w kontekście przeglądarki. */
async function setReloadMarker(page: Page): Promise<void> {
  await page.evaluate(() => {
    ;(window as unknown as Record<string, unknown>).__marker = 1
  })
}

/** Odczytuje znacznik — po nawigacji SPA wciąż `1`, po przeładowaniu `undefined`. */
async function readReloadMarker(page: Page): Promise<unknown> {
  return page.evaluate(() => (window as unknown as Record<string, unknown>).__marker)
}

test('karta zbioru na liście nawiguje routerem bez przeładowania', async ({ page, request }) => {
  test.setTimeout(60_000)

  await resetDb(request)
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, DATASET_NAME)

  try {
    await loginViaUi(page)
    await page.getByRole('navigation').getByRole('link', { name: 'Bazy wiedzy' }).click()
    await expect(page).toHaveURL(/\/datasets$/)
    await expect(page.getByTestId('dataset-card')).toBeVisible()

    await setReloadMarker(page)
    await page.getByRole('link', { name: DATASET_NAME }).click()
    await expect(page).toHaveURL(/\/dataset\/files\//)
    expect(await readReloadMarker(page)).toBe(1)
  } finally {
    await deleteDataset(request, token, datasetId)
  }
})

test('mini-karta na Home nawiguje routerem bez przeładowania', async ({ page, request }) => {
  test.setTimeout(60_000)

  await resetDb(request)
  const token = await apiLogin(request)
  const datasetId = await createDataset(request, token, DATASET_NAME)

  try {
    // `loginViaUi` ląduje na Home — sekcja „ostatnie bazy wiedzy" pokazuje świeży dataset.
    await loginViaUi(page)
    const section = page.getByTestId('home-section-datasets')
    const card = section.getByRole('link', { name: new RegExp(DATASET_NAME) })
    await expect(card).toBeVisible()

    await setReloadMarker(page)
    await card.click()
    await expect(page).toHaveURL(/\/dataset\/files\//)
    expect(await readReloadMarker(page)).toBe(1)
  } finally {
    await deleteDataset(request, token, datasetId)
  }
})
