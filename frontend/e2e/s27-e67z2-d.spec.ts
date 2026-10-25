// Scenariusze SC-E67-z2-16, -17 i -18 (część „Parsing log”) z work/wp/E67-z2/SCENARIOS.md, brief T4:
// wady wizualne z QA-UI E67-z2-1 — niestylowane linki (jasny motyw), przeskok układu zakładek
// datasetu przy 1600 px, menu wiersza pliku (odstęp ikona–etykieta, „+ +” w dialogu metadanych,
// ramka focusu komórki Akcje po kliku myszą) i pusty dialog logu parsowania.
// Testy pisane PRZED poprawkami (czerwone z właściwej przyczyny). Wzorzec: s27-e67z2-a.spec.ts.
import type { APIResponse, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

const SHOTS = process.env.WD_SHOTS_DIR ?? ''
const VIEWPORTS = [
  { name: '1600', width: 1600, height: 900 },
  { name: '1280', width: 1280, height: 800 },
  { name: '390', width: 390, height: 844 },
] as const

const session = uiSession('s27-e67z2-d')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(180_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

let corpus: SeededCorpus
let token = ''
test.beforeAll(async ({ request }) => {
  token = await apiLogin(request)
  corpus = await seedCorpus(request, token, {
    datasetName: `E2E z2d ${Date.now()}`,
    documentName: 'e2e-z2d-sprawozdanie.txt',
    documentBody: 'Sprawozdanie z działalności stowarzyszenia za rok ubiegły, część pierwsza.',
  })
})
test.afterAll(async ({ request }) => {
  await deleteDataset(request, token, corpus.datasetId)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Kolor linku przeglądarki (niestylowany `<a>`) — nie wolno go zobaczyć w aplikacji. */
const BROWSER_DEFAULT_LINK = 'rgb(0, 0, 238)'

async function linkStyle(
  page: Page,
  name: string | RegExp,
): Promise<{ color: string; underline: string }> {
  return page
    .getByRole('link', { name })
    .first()
    .evaluate((el) => ({
      color: getComputedStyle(el).color,
      underline: getComputedStyle(el).textDecorationLine,
    }))
}

for (const vp of VIEWPORTS) {
  test.describe(`E67-z2 T4 ${vp.name}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } })

    test(`SC-E67-z2-16 jasny motyw: link nazwy pliku i „Dokumentacja API” stylowane (${vp.name})`, async ({
      page,
    }) => {
      await page.goto(`/dataset/files/${corpus.datasetId}`)
      await expect(page.getByRole('link', { name: corpus.documentName })).toBeVisible()
      const file = await linkStyle(page, corpus.documentName)
      expect(file.color, 'kolor linku nazwy pliku').not.toBe(BROWSER_DEFAULT_LINK)
      expect(file.underline, 'podkreślenie linku nazwy pliku (poza hoverem)').toBe('none')
      await shot(page, `sc-16-files-${vp.name}`)
      await expectNoLayoutDefects(page, `SC-16 pliki (${vp.name})`)

      await page.goto('/user-setting/api')
      await expect(page.getByRole('link', { name: 'Dokumentacja API' })).toBeVisible()
      const docs = await linkStyle(page, 'Dokumentacja API')
      expect(docs.color, 'kolor linku „Dokumentacja API”').not.toBe(BROWSER_DEFAULT_LINK)
      expect(docs.underline, 'podkreślenie linku „Dokumentacja API”').toBe('none')
      await shot(page, `sc-16-api-${vp.name}`)
    })

    test(`SC-E67-z2-17 menu wiersza: odstęp ikony, dialog bez „+ +”, brak ramki focusu (${vp.name})`, async ({
      page,
    }) => {
      await page.goto(`/dataset/files/${corpus.datasetId}`)
      const row = page.getByRole('row', { name: new RegExp(corpus.documentName) })
      await expect(row).toContainText('Sukces')
      await row.getByTestId('row-actions-menu').click()
      const item = page.getByTestId('row-action-metadata')
      await expect(item).toBeVisible()
      const gap = await item.evaluate((el) => {
        const icon = el.querySelector('svg')
        if (icon === null) return -1
        const range = document.createRange()
        range.selectNodeContents(el.querySelector('.MuiListItemText-root') ?? el)
        return range.getBoundingClientRect().left - icon.getBoundingClientRect().right
      })
      expect(gap, 'odstęp ikona–etykieta w pozycji „Metadane” (px)').toBeGreaterThanOrEqual(8)
      await page.waitForTimeout(400) // koniec animacji menu — czytelny zrzut
      await shot(page, `sc-17-menu-${vp.name}`)
      await expectNoLayoutDefects(page, `SC-17 menu wiersza (${vp.name})`)

      await item.click()
      const dialog = page.getByRole('dialog')
      const add = dialog.getByRole('button', { name: '+ Pole' })
      await expect(add).toBeVisible()
      // Jeden plus: znak w etykiecie albo ikona, nie oba naraz.
      expect(await add.locator('svg').count(), 'ikona obok „+” w przycisku „+ Pole”').toBe(0)
      await page.waitForTimeout(400)
      await shot(page, `sc-17-dialog-${vp.name}`)
      // Formularz czysty (test nie zmienia wartości) — Esc zamyka szufladę od razu,
      // bez dialogu „Odrzucić zmiany?” (SC-V12-07 krok 3).
      await page.keyboard.press('Escape')
      await expect(dialog).toBeHidden()
      await expect(page.getByRole('dialog', { name: 'Odrzucić zmiany?' })).toBeHidden()
    })

    test(`SC-E67-z2-17b brak czerwonej ramki focusu komórki Akcje po kliku myszą (${vp.name})`, async ({
      page,
    }) => {
      await page.goto(`/dataset/files/${corpus.datasetId}`)
      const row = page.getByRole('row', { name: new RegExp(corpus.documentName) })
      await expect(row).toContainText('Sukces')
      await row.getByTestId('row-actions-menu').click()
      await page.getByTestId('row-action-metadata').click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await page.getByRole('dialog').getByRole('button', { name: 'Anuluj' }).click()
      await expect(page.getByRole('dialog')).toBeHidden()
      // Komórka Akcje = ostatnia komórka wiersza z przyciskiem ⋮.
      const cell = row.getByRole('gridcell').filter({ has: page.getByTestId('row-actions-menu') })
      const outline = await cell.evaluate((el) => {
        const style = getComputedStyle(el)
        return { width: parseFloat(style.outlineWidth), style: style.outlineStyle }
      })
      expect(
        outline.style === 'none' || outline.width === 0,
        `ramka komórki Akcje po kliku myszą: ${JSON.stringify(outline)}`,
      ).toBe(true)
      await shot(page, `sc-17b-focus-${vp.name}`)
    })
  })
}

test.describe('E67-z2 T4 zakładki 1600', () => {
  test.use({ viewport: { width: 1600, height: 900 } })

  test('SC-E67-z2-16b zakładki Pliki/Logi/Konfiguracja zaczynają treść w tym samym x', async ({
    page,
  }) => {
    const lefts: Record<string, number[]> = {}
    for (const tab of ['files', 'logs', 'configuration']) {
      await page.goto(`/dataset/${tab}/${corpus.datasetId}`)
      const tablist = page.getByRole('tablist')
      await expect(tablist).toBeVisible()
      // Początek treści: lewa krawędź listy zakładek i nagłówka datasetu.
      lefts[tab] = [
        (await tablist.boundingBox())!.x,
        (await page.getByRole('heading', { level: 1 }).first().boundingBox())!.x,
      ]
      await shot(page, `sc-16b-${tab}`)
    }
    expect(lefts['logs'], 'x listy zakładek i nagłówka: Logi vs Pliki').toEqual(lefts['files'])
    expect(lefts['configuration'], 'x: Konfiguracja vs Pliki').toEqual(lefts['files'])
  })
})

/** Odpowiedź listy dokumentów z wyczyszczonym logiem (jak plik zaimportowany z paczki). */
async function withoutLog(response: APIResponse): Promise<string> {
  const body = (await response.json()) as { data: { docs: Record<string, unknown>[] } }
  body.data.docs = body.data.docs.map((doc) => ({ ...doc, progress_msg: '' }))
  return JSON.stringify(body)
}

for (const vp of VIEWPORTS) {
  test.describe(`E67-z2 T4 log ${vp.name}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } })

    test(`SC-E67-z2-18 „Parsing log” pliku bez logów pokazuje „Brak logu” (${vp.name})`, async ({
      page,
    }) => {
      // Lista z wyczyszczonym `progress_msg` — to samo, co zwraca plik zaimportowany z paczki.
      await page.route(`**/api/v1/datasets/${corpus.datasetId}/documents?*`, async (route) => {
        const response = await route.fetch()
        await route.fulfill({ response, body: await withoutLog(response) })
      })
      await page.goto(`/dataset/files/${corpus.datasetId}`)
      const row = page.getByRole('row', { name: new RegExp(corpus.documentName) })
      await expect(row).toContainText('Sukces')
      await row.getByText('Sukces').click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      await expect(dialog.getByText('Brak logu')).toBeVisible()
      await page.waitForTimeout(400) // koniec animacji dialogu
      await shot(page, `sc-18-log-${vp.name}`)
      await expectNoLayoutDefects(page, `SC-18 pusty log (${vp.name})`)
    })
  })
}

test.describe('E67-z2 T4 ciemny motyw', () => {
  test.use({ viewport: { width: 1280, height: 800 }, colorScheme: 'dark' })

  test('SC-E67-z2-16 ciemny motyw bez regresji: link nazwy pliku, menu wiersza', async ({
    page,
  }) => {
    await page.goto(`/dataset/files/${corpus.datasetId}`)
    const row = page.getByRole('row', { name: new RegExp(corpus.documentName) })
    await expect(row).toContainText('Sukces')
    const file = await linkStyle(page, corpus.documentName)
    expect(file.color, 'kolor linku w ciemnym motywie').not.toBe(BROWSER_DEFAULT_LINK)
    await row.getByTestId('row-actions-menu').click()
    await expect(page.getByTestId('row-action-metadata')).toBeVisible()
    await page.waitForTimeout(400)
    await shot(page, 'dark')
    await expectNoLayoutDefects(page, 'SC-16 ciemny motyw: pliki + menu wiersza')
  })
})
