// Scenariusze SC-E67-z2-01…07 (work/wp/E67-z2/SCENARIOS.md, brief T1): wizualne MINOR-y QA#2 z E67-z1b —
// klucz metadanych z title, dolna ramka akordeonów, placeholdery i etykiety przy 390 px, wiersz
// warunku w szufladzie czatu (≤ 2 linie), Klucze API (centrowanie, nagłówki), moment błędu
// „Klucz jest wymagany”, komunikat „Poczekaj, aż pliki zostaną sparsowane…”.
// Testy pisane PRZED poprawkami (czerwone z właściwej przyczyny). Wzorce: s25-metadata-config.spec.ts,
// s25-metadata-filter.spec.ts (szuflada czatu), s20-mcp-card.spec.ts (Klucze API).
import type { APIRequestContext, APIResponse, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, createDataset, seedCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const DESKTOP = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }
const SHOTS = process.env.WD_SHOTS_DIR ?? ''

let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

const session = uiSession('s27-e67z2-a')
test.use({ storageState: session.statePath })
test.setTimeout(180_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

const cleanupDatasets: string[] = []
test.afterEach(async ({ context, request }) => {
  const token = await adminToken(request)
  for (const id of cleanupDatasets.splice(0)) await deleteDataset(request, token, id)
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

async function newDataset(request: APIRequestContext, label: string): Promise<string> {
  const id = await createDataset(
    request,
    await adminToken(request),
    `E2E z2 ${label} ${Date.now()}`,
  )
  cleanupDatasets.push(id)
  return id
}

/** Konfiguracja datasetu z gotową sekcją „Metadane”. */
async function openConfig(page: Page, datasetId: string): Promise<void> {
  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.getByRole('heading', { name: 'Metadane' })).toBeVisible()
}

const LONG_KEY = 'bardzo_dlugi_klucz_metadanych_ktory_na_pewno_nie_zmiesci_sie_w_polu_64'

test('SC-E67-z2-01 długi klucz metadanych ma pełny title i wielokropek', async ({
  page,
  request,
}) => {
  const datasetId = await newDataset(request, 'klucz')
  await page.setViewportSize(DESKTOP)
  await openConfig(page, datasetId)
  await page.getByRole('button', { name: '+ Pole' }).click()
  const keyInput = page.getByRole('textbox', { name: 'Klucz', exact: true })
  await keyInput.fill(LONG_KEY)
  // Opuszczenie pola (klik w nagłówek sekcji): wielokropek obcina tekst tylko w polu bez fokusu.
  await page.getByRole('heading', { name: 'Metadane' }).click()
  await expect(keyInput).toHaveAttribute('title', LONG_KEY)
  const truncated = await keyInput.evaluate((el: HTMLInputElement) => ({
    overflow: el.scrollWidth > el.clientWidth,
    ellipsis: getComputedStyle(el).textOverflow,
  }))
  expect(truncated).toEqual({ overflow: true, ellipsis: 'ellipsis' })
  await shot(page, 'z2-01-desktop')
  await expectNoLayoutDefects(page, 'konfiguracja: długi klucz metadanych (SC-z2-01)')
})

/** Każdy akordeon bez następnego akordeonu-rodzeństwa musi mieć dolną ramkę. */
async function bottomBorders(page: Page): Promise<{ label: string; width: number }[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll('.MuiAccordion-root')]
      .filter((el) => !el.nextElementSibling?.classList.contains('MuiAccordion-root'))
      .map((el) => ({
        label: el.querySelector('.MuiAccordionSummary-content')?.textContent ?? '?',
        width: parseFloat(getComputedStyle(el).borderBottomWidth),
      })),
  )
}

for (const scheme of ['light', 'dark'] as const) {
  test(`SC-E67-z2-02 akordeony mają dolną ramkę — Konfiguracja i retrieval (${scheme})`, async ({
    page,
    request,
  }) => {
    const datasetId = await newDataset(request, `akordeon ${scheme}`)
    await page.emulateMedia({ colorScheme: scheme })
    await page.setViewportSize(DESKTOP)
    await openConfig(page, datasetId)
    const summary = page.getByRole('button', { name: 'Zaawansowane' }).first()
    await summary.click()
    await summary.click()
    const config = await bottomBorders(page)
    expect(config.length, 'Konfiguracja ma akordeon „Zaawansowane”').toBeGreaterThan(0)
    for (const accordion of config) expect(accordion.width, accordion.label).toBeGreaterThan(0)
    await shot(page, `z2-02-config-${scheme}`)
    await expectNoLayoutDefects(page, `konfiguracja: akordeon (${scheme}, SC-z2-02)`)

    await page.goto(`/dataset/retrieval/${datasetId}`)
    await expect(page.getByRole('button', { name: 'Zaawansowane' })).toBeVisible()
    const retrieval = await bottomBorders(page)
    expect(retrieval.length, 'panel retrievalu ma akordeon').toBeGreaterThan(0)
    for (const accordion of retrieval) expect(accordion.width, accordion.label).toBeGreaterThan(0)
    await shot(page, `z2-02-retrieval-${scheme}`)
  })
}

test('SC-E67-z2-03 390 px: Metadane — pływające etykiety pól widoczne (placeholder „Wartości” tylko od md)', async ({
  page,
  request,
}) => {
  const datasetId = await newDataset(request, 'mobile')
  await page.setViewportSize(MOBILE)
  await openConfig(page, datasetId)
  await page.getByRole('button', { name: '+ Pole' }).click()
  // Poniżej md nagłówek kolumn jest ukryty, a pola mają pływające etykiety (bez placeholdera).
  const values = page.getByRole('combobox', { name: 'Dozwolona wartość' })
  await expect(values).not.toHaveAttribute('placeholder', /.+/)
  // Etykiety pól (Klucz, Opis, Dozwolone wartości) widoczne i nieucięte.
  for (const label of ['Klucz', 'Opis (dla modelu)', 'Dozwolone wartości']) {
    const el = page
      .getByRole('group', { name: 'Pole 1' })
      .locator('label', { hasText: label })
      .first()
    await expect(el, `etykieta ${label}`).toBeVisible()
    const clipped = await el.evaluate((node) => node.scrollWidth > node.clientWidth)
    expect(clipped, `etykieta ${label} nieucięta`).toBe(false)
  }
  await shot(page, 'z2-03-mobile')
  await expectNoLayoutDefects(page, 'konfiguracja: pole metadanych 390 px (SC-z2-03)')
})

test('SC-E67-z2-04 390 px: szuflada czatu — warunek z placeholderami w ≤ 2 liniach', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const { datasetId, documentId } = await seedCorpus(request, token, {
    datasetName: `E2E z2 czat ${Date.now()}`,
    documentName: 'e2e-z2-czat.txt',
    documentBody:
      'Raport roczny o stanie powietrza w Krakowie za rok dwa tysiące dwudziesty trzeci.',
  })
  cleanupDatasets.push(datasetId)
  // Metadane dokumentu — bez nich kreator pokazuje tylko „Bazy nie mają metadanych”.
  const patched = await request.patch(
    `${API_URL}/api/v1/datasets/${datasetId}/documents/${documentId}`,
    { headers: { authorization: `Bearer ${token}` }, data: { meta_fields: { typ: 'raport' } } },
  )
  expect(patched.status()).toBe(200)
  const chatId = await createChat(request, token, {
    name: `E2E z2 czat ${Date.now()}`,
    datasetIds: [datasetId],
  })
  await page.setViewportSize(MOBILE)
  await page.goto(`/chat/${chatId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  const advanced = page.getByRole('button', { name: 'Zaawansowane' })
  if ((await advanced.getAttribute('aria-expanded')) === 'false') await advanced.click()
  await page.getByText('Filtr metadanych', { exact: true }).click()
  await page.getByRole('radio', { name: 'Ręczny' }).check()
  // „Ręczny” sam dodaje „Warunek 1” — dopiero na ustabilizowanym układzie klikamy „+ Warunek”.
  await expect(page.getByRole('group', { name: 'Warunek 1' })).toBeVisible()
  await page.getByRole('button', { name: '+ Warunek' }).click()
  const row = page.getByRole('group', { name: 'Warunek 2' })
  await expect(row).toBeVisible()
  // Nowy wiersz jest pusty: oba pola mają placeholder.
  await expect(row.getByRole('combobox', { name: 'Klucz' })).toHaveAttribute('placeholder', /\S/)
  await expect(row.getByRole('combobox', { name: 'Wartość' })).toHaveAttribute('placeholder', /\S/)
  // Liczba linii = liczba pionowych pozycji dzieci wiersza (kosz ma odsunięcie 3 px — klaster ≤ 8 px).
  const lines = await row.evaluate((el) => {
    const tops = [...el.children]
      .map((child) => child.getBoundingClientRect().top)
      .sort((a, b) => a - b)
    return tops.filter((top, i) => i === 0 || top - tops[i - 1]! > 8).length
  })
  expect(lines, 'wiersz warunku zajmuje najwyżej 2 linie').toBeLessThanOrEqual(2)
  await shot(page, 'z2-04-mobile')
  await expectNoLayoutDefects(page, 'szuflada czatu: wiersz warunku 390 px (SC-z2-04)')
})

test('SC-E67-z2-05 390 px: Klucze API — akcje wyśrodkowane, nagłówki nieucięte', async ({
  page,
}) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/user-setting/api')
  await page.getByRole('button', { name: 'Utwórz klucz' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Utwórz', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Zamknij' }).click()
  const row = page
    .getByRole('grid', { name: 'Klucze API' })
    .locator('[role="row"][data-id]')
    .first()
  await expect(row).toBeVisible()
  const offsets = await row.evaluate((rowEl) => {
    const rowRect = rowEl.getBoundingClientRect()
    const rowCenter = rowRect.top + rowRect.height / 2
    return [...rowEl.querySelectorAll('button')].map((button) => {
      const rect = button.getBoundingClientRect()
      return Math.abs(rect.top + rect.height / 2 - rowCenter)
    })
  })
  expect(offsets.length, 'wiersz ma przycisk akcji').toBeGreaterThan(0)
  for (const offset of offsets) expect(offset).toBeLessThanOrEqual(2)
  const clippedHeaders = await page.evaluate(() =>
    [...document.querySelectorAll('.MuiDataGrid-columnHeaderTitle')]
      .filter((el) => el.scrollWidth > el.clientWidth)
      .map((el) => el.textContent),
  )
  expect(clippedHeaders, 'nagłówki kolumn nieucięte').toEqual([])
  // Wszystkie nagłówki mieszczą się w oknie siatki — bez poziomego przewijania ucinającego „Utworzono”.
  const overflow = await page.evaluate(() => {
    const scroller = document.querySelector('.MuiDataGrid-virtualScroller')
    const grid = document.querySelector('.MuiDataGrid-root')
    return {
      scrollable: (scroller?.scrollWidth ?? 0) - (scroller?.clientWidth ?? 0),
      headersOutside: [...document.querySelectorAll('.MuiDataGrid-columnHeader')]
        .filter(
          (el) => el.getBoundingClientRect().right > (grid?.getBoundingClientRect().right ?? 0) + 1,
        )
        .map((el) => el.textContent),
    }
  })
  expect(overflow, 'siatka kluczy bez poziomego przewijania').toEqual({
    scrollable: 0,
    headersOutside: [],
  })
  await shot(page, 'z2-05-mobile')
  await expectNoLayoutDefects(page, 'Klucze API 390 px (SC-z2-05)')
})

test('SC-E67-z2-06 „Klucz jest wymagany” dopiero po opuszczeniu pola', async ({
  page,
  request,
}) => {
  const datasetId = await newDataset(request, 'wymagany')
  await page.setViewportSize(DESKTOP)
  await openConfig(page, datasetId)
  await page.getByRole('button', { name: '+ Pole' }).click()
  await expect(page.getByRole('textbox', { name: 'Klucz', exact: true })).toBeFocused()
  await expect(page.getByText('Klucz jest wymagany')).toHaveCount(0)
  await shot(page, 'z2-06-desktop')
  await page.getByRole('group', { name: 'Pole 1' }).getByRole('textbox', { name: 'Opis' }).click()
  await expect(page.getByText('Klucz jest wymagany')).toBeVisible()
  // Etykieta pola „Opis” po kliknięciu jeszcze się animuje (zmniejsza) — czekamy na koniec przejścia.
  await page.waitForTimeout(400)
  await expectNoLayoutDefects(page, 'konfiguracja: błąd klucza po blur (SC-z2-06)')
})

/** Odpowiedź listy dokumentów z jednym dokumentem przestawionym na parsowanie. */
async function asRunning(response: APIResponse): Promise<string> {
  const body = (await response.json()) as { data: { docs: Record<string, unknown>[] } }
  body.data.docs = body.data.docs.map((doc) => ({ ...doc, run: 'RUNNING', progress: 0.4 }))
  return JSON.stringify(body)
}

test('SC-E67-z2-07 komunikat „Poczekaj…” tylko gdy plik się parsuje', async ({ page, request }) => {
  const token = await adminToken(request)
  const { datasetId } = await seedCorpus(request, token, {
    datasetName: `E2E z2 pliki ${Date.now()}`,
    documentName: 'e2e-z2-pliki.txt',
    documentBody: 'Sprawozdanie z działalności stowarzyszenia za rok ubiegły, część pierwsza.',
  })
  cleanupDatasets.push(datasetId)
  const message = page.getByText('Poczekaj, aż pliki zostaną sparsowane', { exact: false })
  await page.setViewportSize(DESKTOP)
  await page.goto(`/dataset/files/${datasetId}`)
  const doneRow = page.getByRole('row', { name: /e2e-z2-pliki\.txt/ })
  await expect(doneRow).toContainText('Sukces')
  await expect(message).toHaveCount(0)
  await shot(page, 'z2-07-desktop')
  await expectNoLayoutDefects(page, 'pliki: status Sukces bez komunikatu (SC-z2-07)')

  // Wariant „plik w parsowaniu”: ta sama lista z przestawionym statusem (parsowanie fake-llm
  // kończy się szybciej, niż da się je złapać stabilnie).
  await page.route(`**/api/v1/datasets/${datasetId}/documents?*`, async (route) => {
    const response = await route.fetch()
    await route.fulfill({ response, body: await asRunning(response) })
  })
  await page.reload()
  await expect(message).toBeVisible()
  await shot(page, 'z2-07-parsing')
  await expectNoLayoutDefects(page, 'pliki: plik w parsowaniu z komunikatem (SC-z2-07)')
})
