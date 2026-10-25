// Scenariusze SC-E67-z2-24…27 z work/wp/E67-z2/SCENARIOS.md, brief T8: wady wizualne z QA-UI E67-z2-2 —
// tło komórek tabeli plików i nagłówek „Actions” (EN, 390), urwane zdanie filtra metadanych w czacie
// bez bazy, placeholdery/etykiety formularza pól metadanych i szuflady, obrys „Model indeksujący”,
// menu ⋮ karty bazy (ikony) i waga tytułu okna „Eksportuj”.
// Testy pisane PRZED poprawkami (czerwone z właściwej przyczyny). Wzorzec: s27-e67z2-d.spec.ts.
import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, createDataset, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const SHOTS = process.env.WD_SHOTS_DIR ?? ''
const LONG_KEY = 'bardzo_dlugi_klucz_metadanych_do_testow_wielokropka_na_liscie_kluczy'

const session = uiSession('s27-e67z2-f')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(240_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

let corpus: SeededCorpus
let emptyDatasetId = ''
let chatNoDatasetId = ''
let chatWithDatasetId = ''
let token = ''
const datasetName = `E2E z2f ${Date.now()}`
test.beforeAll(async ({ request }) => {
  token = await apiLogin(request)
  corpus = await seedCorpus(request, token, {
    datasetName,
    documentName: 'e2e-z2f-sprawozdanie-z-dzialalnosci.txt',
    documentBody: 'Sprawozdanie z działalności stowarzyszenia za rok ubiegły, część pierwsza.',
  })
  const patched = await request.patch(
    `${API_URL}/api/v1/datasets/${corpus.datasetId}/documents/${corpus.documentId}`,
    {
      headers: { authorization: `Bearer ${token}` },
      data: { meta_fields: { rok: '2023', [LONG_KEY]: 'x' } },
    },
  )
  expect(((await patched.json()) as { code: number }).code, 'PATCH meta_fields').toBe(0)
  emptyDatasetId = await createDataset(request, token, `E2E z2f pusta ${Date.now()}`)
  chatNoDatasetId = await createChat(request, token, {
    name: `E2E z2f czat bez bazy ${Date.now()}`,
  })
  chatWithDatasetId = await createChat(request, token, {
    name: `E2E z2f czat z baza ${Date.now()}`,
    datasetIds: [corpus.datasetId],
  })
})
test.afterAll(async ({ request }) => {
  await deleteDataset(request, token, corpus.datasetId)
  await deleteDataset(request, token, emptyDatasetId)
  for (const id of [chatNoDatasetId, chatWithDatasetId]) {
    await request.delete(`${API_URL}/api/v1/chats`, {
      headers: { authorization: `Bearer ${token}` },
      data: { ids: [id] },
    })
  }
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Tło widoczne pod komórką: pierwszy przodek (łącznie z nią) z nieprzezroczystym `background-color`. */
function visibleBackground(cell: Locator): Promise<string> {
  return cell.evaluate((el) => {
    let node: Element | null = el
    while (node !== null) {
      const color = getComputedStyle(node).backgroundColor
      if (!/rgba\(.*, 0\)$/.test(color) && color !== 'transparent') return color
      node = node.parentElement
    }
    return 'none'
  })
}

for (const [name, width, height] of [
  ['1280', 1280, 800],
  ['1600', 1600, 900],
] as const) {
  test(`SC-E67-z2-24 tabela plików ${name} jasny: tło komórek jednolite w całym wierszu`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height })
    await page.goto(`/dataset/files/${corpus.datasetId}`)
    const row = page.getByRole('row', { name: new RegExp(corpus.documentName) })
    await expect(row).toContainText('Sukces')
    const nameBg = await visibleBackground(row.locator('[data-field="name"]'))
    const dateBg = await visibleBackground(row.locator('[data-field="create_time"]'))
    const statusBg = await visibleBackground(row.locator('[data-field="run"]'))
    expect(nameBg, 'tło komórki „Nazwa” = tło komórki „Data przesłania”').toBe(dateBg)
    expect(statusBg, 'tło komórki „Status” = tło komórki „Data przesłania”').toBe(dateBg)
    await shot(page, `sc-24-files-${name}`)
    await expectNoLayoutDefects(page, `SC-24 tabela plików (${name})`)
  })
}

test('SC-E67-z2-24 390 EN: nagłówek „Actions” tabeli plików nieucięty', async ({
  page,
  request,
}) => {
  await setProfileLanguage(request, token, 'en')
  try {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`/dataset/files/${corpus.datasetId}`)
    const header = page.locator('[role="columnheader"][data-field="actions"]')
    await expect(header).toBeVisible()
    await expect(header).toContainText('Actions')
    const clipped = await header
      .locator('.MuiDataGrid-columnHeaderTitle')
      .evaluate((el) => el.scrollWidth > el.clientWidth + 1)
    expect(clipped, 'nagłówek „Actions” ucięty (scrollWidth > clientWidth)').toBe(false)
    await shot(page, 'sc-24-files-390-en')
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})

test('SC-E67-z2-25 czat bez bazy → Zaawansowane → Filtr metadanych: zdanie dokończone', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/chat/${chatNoDatasetId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  const advanced = page.getByRole('button', { name: 'Zaawansowane' })
  if ((await advanced.getAttribute('aria-expanded')) === 'false') await advanced.click()
  await page.getByText('Filtr metadanych', { exact: true }).click()
  const sentence = page.getByText(/Bazy nie mają metadanych/)
  await expect(sentence).toBeVisible()
  const text = ((await sentence.textContent()) ?? '').trim()
  expect(text, 'zdanie nie może urywać się na przyimku „w”').not.toMatch(/\sw$/)
  expect(text, 'zdanie kończy się kropką').toMatch(/\.$/)
  await page.waitForTimeout(400) // koniec animacji akordeonów
  await shot(page, 'sc-25-chat-nodataset')
  await expectNoLayoutDefects(page, 'SC-25 czat bez bazy: filtr metadanych')
})

test('SC-E67-z2-26 Konfiguracja → Metadane 1280: placeholdery nieucięte, jedna etykieta „Klucz”', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/configuration/${emptyDatasetId}`)
  await page.getByRole('button', { name: '+ Pole' }).click()
  const group = page.getByRole('group', { name: 'Pole 1' })
  await expect(group).toBeVisible()
  // Etykieta „Klucz” raz: nagłówek kolumny albo pływająca etykieta pola — nie oba naraz.
  await expect(
    page.getByText('Klucz', { exact: true }),
    'etykieta „Klucz” (nagłówek+pole)',
  ).toHaveCount(1)
  // Teksty widoczne w polach (etykieta pływająca / placeholder) mieszczą się w polu.
  const clipped = await group.evaluate((root) => {
    const canvas = document.createElement('canvas').getContext('2d')!
    const problems: string[] = []
    for (const label of root.querySelectorAll<HTMLElement>('.MuiInputLabel-root')) {
      if (label.scrollWidth > label.clientWidth + 1)
        problems.push(`etykieta „${label.textContent}”`)
    }
    for (const input of root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
      'input[placeholder], textarea[placeholder]',
    )) {
      const style = getComputedStyle(input)
      canvas.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
      const textWidth = canvas.measureText(input.placeholder).width
      const inner =
        input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
      if (textWidth > inner + 1) problems.push(`placeholder „${input.placeholder}”`)
    }
    return problems
  })
  expect(clipped, 'teksty pól ucięte w formularzu pola metadanych').toEqual([])
  await shot(page, 'sc-26-meta-config-1280')
  await expectNoLayoutDefects(page, 'SC-26 Konfiguracja → Metadane (1280)')
})

test('SC-E67-z2-26 Konfiguracja → Zaawansowane: strzałka „Model indeksujący” wewnątrz obrysu pola', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/configuration/${emptyDatasetId}`)
  await page.getByRole('button', { name: 'Zaawansowane' }).click()
  const field = page.getByRole('combobox', { name: 'Model indeksujący' })
  await expect(field).toBeVisible()
  const root = field.locator('xpath=ancestor::*[contains(@class,"MuiOutlinedInput-root")][1]')
  const arrow = root.locator('.MuiAutocomplete-popupIndicator')
  const outer = (await root.boundingBox())!
  const inner = (await arrow.boundingBox())!
  expect(inner.y - outer.y, 'odstęp strzałki od górnej krawędzi obrysu').toBeGreaterThanOrEqual(2)
  expect(
    outer.y + outer.height - (inner.y + inner.height),
    'odstęp strzałki od dolnej krawędzi obrysu',
  ).toBeGreaterThanOrEqual(2)
  expect(
    outer.x + outer.width - (inner.x + inner.width),
    'odstęp strzałki od prawej krawędzi obrysu',
  ).toBeGreaterThanOrEqual(4)
  await shot(page, 'sc-26-model-indeksujacy')
})

test('SC-E67-z2-26 szuflada „Metadane” pliku: widoczne etykiety „Klucz” i „Wartość”', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/dataset/files/${corpus.datasetId}`)
  const row = page.getByRole('row', { name: new RegExp(corpus.documentName) })
  await expect(row).toContainText('Sukces')
  await row.getByTestId('row-actions-menu').click()
  await page.getByTestId('row-action-metadata').click()
  const drawer = page.getByRole('dialog')
  await expect(drawer).toBeVisible()
  await drawer.getByRole('button', { name: '+ Pole' }).click()
  await expect(drawer.locator('.MuiInputLabel-root', { hasText: /^Klucz$/ }).first()).toBeVisible()
  await expect(
    drawer.locator('.MuiInputLabel-root', { hasText: /^Wartość$/ }).first(),
  ).toBeVisible()
  await page.waitForTimeout(400)
  await shot(page, 'sc-26-drawer')
  await expectNoLayoutDefects(page, 'SC-26 szuflada metadanych pliku')
})

test('SC-E67-z2-26 czat (ciemny) → Ręczny: długi klucz na liście z wielokropkiem', async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/chat/${chatWithDatasetId}`)
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  const advanced = page.getByRole('button', { name: 'Zaawansowane' })
  if ((await advanced.getAttribute('aria-expanded')) === 'false') await advanced.click()
  await page.getByText('Filtr metadanych', { exact: true }).click()
  await page.getByRole('radio', { name: 'Ręczny' }).check()
  await page.getByRole('combobox', { name: 'Klucz' }).first().click()
  const option = page.getByRole('option', { name: LONG_KEY })
  await expect(option).toBeVisible()
  const style = await option.evaluate((el) => ({
    clipped: el.scrollWidth > el.clientWidth + 1,
    ellipsis: getComputedStyle(el).textOverflow === 'ellipsis',
    inner: [...el.querySelectorAll('*')].some(
      (e) => getComputedStyle(e).textOverflow === 'ellipsis',
    ),
  }))
  expect(
    !style.clipped || style.ellipsis || style.inner,
    `długi klucz na liście ucięty bez wielokropka: ${JSON.stringify(style)}`,
  ).toBe(true)
  await shot(page, 'sc-26-chat-keys-dark')
})

test('SC-E67-z2-27 menu ⋮ karty bazy: wszystkie pozycje z ikoną; tytuł „Eksportuj” jak inne okna', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/datasets')
  const card = page.getByTestId('dataset-card').filter({ hasText: datasetName }).first()
  await expect(card).toBeVisible()
  await card.getByRole('button').last().click()
  const menu = page.getByRole('menu')
  await expect(menu).toBeVisible()
  const items = menu.getByRole('menuitem')
  expect(await items.count()).toBeGreaterThanOrEqual(3)
  for (const item of await items.all()) {
    expect(await item.locator('svg').count(), `ikona pozycji „${await item.textContent()}”`).toBe(1)
  }
  // Wyrównanie: etykiety zaczynają się w tym samym x.
  const lefts = await items.evaluateAll((els) =>
    els.map((el) => {
      const range = document.createRange()
      range.selectNodeContents(el.querySelector('.MuiListItemText-root') ?? el)
      return Math.round(range.getBoundingClientRect().left)
    }),
  )
  expect(new Set(lefts).size, `etykiety menu w jednym x: ${lefts.join(',')}`).toBe(1)
  await page.waitForTimeout(400)
  await shot(page, 'sc-27-card-menu')

  // Tytuł „Zmień nazwę” (dialog sąsiedni) jako wzorzec wagi.
  await menu.getByRole('menuitem', { name: 'Zmień nazwę' }).click()
  const renameTitle = page.getByRole('dialog').locator('.MuiDialogTitle-root').first()
  await expect(renameTitle).toBeVisible()
  const renameWeight = await renameTitle.evaluate((el) => getComputedStyle(el).fontWeight)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeHidden()

  await card.getByRole('button').last().click()
  await page.getByRole('menuitem', { name: 'Eksportuj' }).click()
  const exportDialog = page.getByRole('dialog')
  await expect(exportDialog).toBeVisible()
  const titleText = exportDialog.locator('.MuiDialogTitle-root [aria-label]').first()
  await expect(titleText).toBeVisible()
  const exportWeight = await titleText.evaluate((el) => getComputedStyle(el).fontWeight)
  expect(exportWeight, 'waga tytułu okna „Eksportuj” = waga tytułu innych okien').toBe(renameWeight)
  await page.waitForTimeout(400)
  await shot(page, 'sc-27-export-dialog')
})
