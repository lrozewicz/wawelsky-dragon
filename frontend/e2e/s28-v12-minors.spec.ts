// T7 WP V12-2 — CONTRACT (b) M1–M4: cztery MINOR-y front-only (brief work/wp/V12-2/tasks/T7-minors.md):
// M1 kolumna „Nazwa” przy 1280 px (bez „Metody chunkowania” < xl), M2 dolna linia ostatniego
// wiersza pod przyklejoną komórką „Nazwa” (jasny/ciemny), M3 opis trybów filtra metadanych
// („Ręczny” itd.), M4 placeholder „Dozwolone wartości” nieucięty przy 1280 px.
// Testy pisane PRZED poprawkami (czerwone z właściwej przyczyny → work/wp/V12-2/reports/T7-red.log).
// Wzorzec: s27-e67z2-c.spec.ts.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, createDataset } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const SHOTS = process.env.WD_SHOTS_DIR ?? ''
const DESKTOP = { width: 1280, height: 800 }
const WIDE = { width: 1600, height: 900 }

const FILE_A = 'gus_pracujacy_w_gospodarce_narodowej_2025.txt'
const FILE_B = 'gus_rocznik_statystyczny_rzeczypospolitej_2025.txt'
const TXT_PATH = fileURLToPath(new URL('./fixtures/metadata-rok-typ.txt', import.meta.url))

const session = uiSession('s28-v12-minors')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(180_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

let token = ''
let datasetId = ''
let chatId = ''
const datasetName = `E2E v12m ${Date.now()}`
test.beforeAll(async ({ request }) => {
  token = await apiLogin(request)
  datasetId = await createDataset(request, token, datasetName)
  const headers = { authorization: `Bearer ${token}` }
  for (const fileName of [FILE_A, FILE_B]) {
    const response = await request.post(`${API_URL}/api/v1/datasets/${datasetId}/documents`, {
      headers,
      multipart: {
        file: { name: fileName, mimeType: 'text/plain', buffer: readFileSync(TXT_PATH) },
      },
    })
    const body = (await response.json()) as { code: number; message: string }
    expect(body.code, `upload ${fileName}: ${body.message}`).toBe(0)
  }
  // Czat bez baz — kreator filtra metadanych w Ustawieniach czatu pokazuje pełny przełącznik trybów.
  chatId = await createChat(request, token, { name: `E2E v12m czat ${Date.now()}` })
})
test.afterAll(async ({ request }) => {
  await deleteDataset(request, token, datasetId)
  await request.delete(`${API_URL}/api/v1/chats`, {
    headers: { authorization: `Bearer ${token}` },
    data: { ids: [chatId] },
  })
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

async function openFiles(page: Page): Promise<void> {
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: datasetName })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: FILE_A })).toBeVisible()
}

test('C5-M1 1280: kolumna „Metoda chunkowania” ukryta, „Nazwa” ≥ 200 px; 1600: „Metoda” widoczna', async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  await openFiles(page)

  // Poniżej xl (1536 px) „Metoda chunkowania” schodzi z listy kolumn (s18 nie sprawdza nagłówków).
  const methodHeader = page.getByRole('columnheader', { name: 'Metoda chunkowania' })
  await expect(methodHeader).toHaveCount(0)

  // Komórka „Nazwa” (boundingBox) ma ≥ 200 px — ok. 30 znaków nazwy w 1–2 liniach.
  const nameCell = page.getByRole('row').filter({ hasText: FILE_B }).locator('[data-field="name"]')
  await expect(nameCell).toBeVisible()
  const box = await nameCell.boundingBox()
  expect(box, 'komórka „Nazwa” ma prostokąt').not.toBeNull()
  expect(
    box!.width,
    `szerokość komórki „Nazwa” przy 1280 px (mierzone: ${box!.width})`,
  ).toBeGreaterThanOrEqual(200)
  await shot(page, 'v12m-m1-1280')
  await expectNoLayoutDefects(page, 'C5-M1 tabela plików 1280')

  // ≥ xl metoda wraca (informacja nie ginie na dużym ekranie).
  await page.setViewportSize(WIDE)
  await expect(page.getByRole('columnheader', { name: 'Metoda chunkowania' })).toBeVisible()
})

for (const scheme of ['light', 'dark'] as const) {
  test(`C5-M2 1280 ${scheme}: ostatni wiersz ma dolną linię pod komórką „Nazwa”`, async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP)
    await page.emulateMedia({ colorScheme: scheme })
    await openFiles(page)

    // Ostatni wiersz siatki (dwa pliki, sortowanie domyślne) — komórka „Nazwa” z własnym
    // dolnym oddzieleniem jak pozostałe wiersze (computed style, motyw jasny i ciemny).
    const lastRow = page.locator('.MuiDataGrid-virtualScrollerContent .MuiDataGrid-row').last()
    await expect(lastRow).toBeVisible()
    await expect(lastRow.filter({ hasText: FILE_A })).toBeVisible()
    const nameCell = lastRow.locator('[data-field="name"]')
    const borderBottom = await nameCell.evaluate((el) =>
      parseFloat(getComputedStyle(el).borderBottomWidth),
    )
    expect(
      borderBottom,
      `dolna ramka ostatniej komórki „Nazwa” (${scheme}, mierzone: ${borderBottom})`,
    ).toBeGreaterThan(0)
    await shot(page, `v12m-m2-last-row-${scheme}`)
  })
}

test('C5-M3 opis trybu filtra metadanych istnieje i nie jest pusty („Ręczny” i inny)', async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  // Kreator metadanych siedzi w „Zaawansowane” → „Filtr metadanych” (dwuszczeblowy akordeon).
  await page.getByRole('button', { name: 'Zaawansowane' }).click()
  await page.getByRole('button', { name: 'Filtr metadanych' }).click()

  const description = page.getByTestId('metadata-mode-desc')
  // Tryb początkowy (Wyłączony) ma opis…
  await expect(description).toBeVisible()
  const off = await description.textContent()
  expect(off?.trim().length ?? 0, 'opis trybu „Wyłączony” niepusty').toBeGreaterThan(0)

  // …po zmianie trybu na „Ręczny” opis istnieje, nie jest pusty i inny niż dla „Wyłączonego”.
  await page.getByRole('radio', { name: 'Ręczny' }).check()
  await expect(description).toBeVisible()
  const manual = await description.textContent()
  expect(manual?.trim().length ?? 0, 'opis trybu „Ręczny” niepusty').toBeGreaterThan(0)
  expect(manual, 'opis „Ręczny” różni się od „Wyłączonego”').not.toBe(off)
  await shot(page, 'v12m-m3-mode-desc')
})

test('C5-M4 1280: placeholder pola „Dozwolone wartości” mieści się w polu (bez ucięcia)', async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.getByRole('heading', { name: 'Metadane' })).toBeVisible()
  await page.getByRole('button', { name: '+ Pole' }).click()

  const values = page.getByRole('combobox', { name: 'Dozwolona wartość' })
  await expect(values).toBeVisible()
  // Pole z placeholderem nie przewija w poziomie: scrollWidth ≤ clientWidth (przy 1280 px).
  const fits = await values.evaluate(
    (el) => (el as HTMLInputElement).scrollWidth <= (el as HTMLInputElement).clientWidth,
  )
  expect(fits, 'placeholder mieści się w polu (scrollWidth ≤ clientWidth)').toBe(true)
  await shot(page, 'v12m-m4-placeholder')
  await expectNoLayoutDefects(page, 'C5-M4 pole metadanych 1280')
})
