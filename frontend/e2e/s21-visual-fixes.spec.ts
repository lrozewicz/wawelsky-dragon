// SC-E5-H8z-03 (brief T5 — wady z przeglądu wzorców visual T2): cztery defekty widoczne na
// zrzutach wzorcowych, każdy z asercją geometryczną, czerwony na bazie:
//   (a) profil 390: „Nie ustawiono” łamane w środek słowa (`word-break` w wąskiej kolumnie);
//   (b) czat 1280 (rail zwinięty — trasa `fullBleed`): przycisk menu użytkownika u dołu raila
//       ucięty prawą krawędzią (awatar + przycisk nie mieszczą się w 64 px);
//   (c) admin 390: ~40 px pustki przed pierwszą zakładką (zarezerwowane pod przycisk
//       przewijania MUI Tabs);
//   (d) lista plików datasetu 390: filtry i „Prześlij plik” wcięte 16 px względem pola
//       „Szukaj plików” (`margin-left` ze Stack `spacing` na zawiniętych elementach).
import type { APIRequestContext } from '@playwright/test'

import { expect, test } from './fixtures'

import { apiLogin, createChat, deleteAllChats, seedCorpus } from './helpers'
import { uiSession } from './helpers/session'

// Logowanie RAZ na plik (T11): limiter logowań (10/min per IP+e-mail, CONTRACT E5-2a §4) jest
// współdzielony z całym biegiem — patrz helpers/session.ts. UWAGA: w beforeAll tylko `browser` —
// fixture `request` w sygnaturze hooka każe Playwrightowi utworzyć kontekst testu (z jeszcze
// nieistniejącym `storageState`) PRZED hookiem i połyka błąd hooka; dane seedujemy leniwie
// w testach (wzór: memoizacja tokenu z s17).
const session = uiSession('s21-visual-fixes')
test.use({ storageState: session.statePath })
test.setTimeout(90_000)

const DOC_NAME = 's21-raport-rynek-pracy.txt'
const DOC_BODY =
  'Akapit próbny. Stopa bezrobocia rejestrowana w Polsce spadała do końca 2022 roku, ' +
  'a według BAEL pozostała stabilna. Dane pochodzą z tablic rynku pracy GUS.'

let tokenPromise: Promise<string> | undefined
function token(request: APIRequestContext): Promise<string> {
  tokenPromise ??= apiLogin(request)
  return tokenPromise
}

let chatIdPromise: Promise<string> | undefined
/** Czat dla punktu (b) — tworzymy raz, leniwie (pierwsze użycie w teście). */
function chatId(request: APIRequestContext): Promise<string> {
  chatIdPromise ??= token(request).then((auth) =>
    createChat(request, auth, { name: 's21 — rail mini' }),
  )
  return chatIdPromise
}

let datasetIdPromise: Promise<string> | undefined
/** Korpus dla punktu (d) — seedujemy raz, leniwie (parsowanie dokumentu trwa sekundy). */
function datasetId(request: APIRequestContext): Promise<string> {
  datasetIdPromise ??= (async () => {
    const auth = await token(request)
    const corpus = await seedCorpus(request, auth, {
      datasetName: 's21 — pliki datasetu',
      documentName: DOC_NAME,
      documentBody: DOC_BODY,
    })
    return corpus.datasetId
  })()
  return datasetIdPromise
}

test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

test.afterEach(async ({ context }) => {
  await session.save(context)
})

test.describe('SC-E5-H8z-03 (a) profil 390', () => {
  test.use({ viewport: { width: 390, height: 844 }, colorScheme: 'light' })

  test('„Nie ustawiono” łamie się tylko między słowami, bez rozerwania i bez ucięcia', async ({
    page,
  }) => {
    await page.goto('/user-setting/profile')
    const row = page.getByTestId('profile-row-timezone')
    await expect(row).toBeVisible()
    const value = row.getByText('Nie ustawiono')
    await expect(value).toBeVisible()

    // Sedno defektu: słowo „ustawiono” rozerwane w środku (2 fragmenty linii zamiast 1).
    const wordRects = await value.evaluate((el) => {
      const node = el.firstChild
      if (node === null || node.nodeType !== Node.TEXT_NODE) return -1
      const text = node.textContent ?? ''
      const start = text.indexOf('ustawiono')
      if (start === -1) return -1
      const range = document.createRange()
      range.setStart(node, start)
      range.setEnd(node, start + 'ustawiono'.length)
      return range.getClientRects().length
    })
    expect(
      wordRects,
      'słowo „ustawiono” ma być jednym fragmentem linii (bez rozerwania w środku słowa)',
    ).toBe(1)

    const metrics = await value.evaluate((el) => {
      const style = getComputedStyle(el)
      const lineHeight = Number.parseFloat(style.lineHeight)
      const line = Number.isNaN(lineHeight) ? Number.parseFloat(style.fontSize) * 1.5 : lineHeight
      return {
        height: el.getBoundingClientRect().height,
        twoLines: 2 * line + 1,
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
      }
    })
    expect(metrics.height, 'wartość na co najwyżej dwóch liniach').toBeLessThanOrEqual(
      metrics.twoLines,
    )
    expect(
      metrics.scrollWidth,
      'wartość nie wychodzi poziomo poza swój element',
    ).toBeLessThanOrEqual(metrics.clientWidth)

    await page.screenshot({ path: '../.task/shots/s21-profil-390.png' })
  })
})

test.describe('SC-E5-H8z-03 (b) czat 1280, rail zwinięty', () => {
  test.use({ viewport: { width: 1280, height: 800 }, colorScheme: 'dark' })

  test('każdy przycisk raila mieści się w całości w jego granicach', async ({ page, request }) => {
    await page.goto(`/chat/${await chatId(request)}`)
    const rail = page.locator('.MuiDrawer-docked .MuiDrawer-paper')
    await expect(rail).toBeVisible()
    const railBox = await rail.boundingBox()
    expect(railBox, 'boundingBox raila').not.toBeNull()

    const buttons = rail.locator('button')
    const count = await buttons.count()
    expect(count, 'rail ma przyciski (zwijanie, menu użytkownika)').toBeGreaterThanOrEqual(2)

    for (let i = 0; i < count; i += 1) {
      const box = await buttons.nth(i).boundingBox()
      expect(box, `przycisk #${i} ma boundingBox`).not.toBeNull()
      const left = box!.x
      const right = box!.x + box!.width
      const top = box!.y
      const bottom = box!.y + box!.height
      expect(
        left >= railBox!.x - 1 &&
          right <= railBox!.x + railBox!.width + 1 &&
          top >= railBox!.y - 1 &&
          bottom <= railBox!.y + railBox!.height + 1,
        `przycisk #${i} (${left}…${right}, ${top}…${bottom}) ma być w railu (${railBox!.x}…${railBox!.x + railBox!.width}, ${railBox!.y}…${railBox!.y + railBox!.height})`,
      ).toBe(true)
    }

    await page.screenshot({ path: '../.task/shots/s21-rail-mini-1280.png' })
  })
})

test.describe('SC-E5-H8z-03 (c) admin 390', () => {
  test.use({ viewport: { width: 390, height: 844 }, colorScheme: 'light' })

  test('pierwsza zakładka zaczyna przy lewej krawędzi treści (bez luki na przyciski przewijania)', async ({
    page,
  }) => {
    await page.goto('/admin/users')
    const heading = page.getByRole('heading', { name: 'Administracja' })
    await expect(heading).toBeVisible()
    const firstTab = page.getByTestId('admin-tab-users')
    await expect(firstTab).toBeVisible()

    const headingBox = await heading.boundingBox()
    const tabBox = await firstTab.boundingBox()
    expect(headingBox, 'boundingBox nagłówka').not.toBeNull()
    expect(tabBox, 'boundingBox pierwszej zakładki').not.toBeNull()
    expect(
      tabBox!.x,
      `lewa krawędź pierwszej zakładki (${tabBox!.x}) ≤ lewa krawędź nagłówka + 4 px (${headingBox!.x + 4})`,
    ).toBeLessThanOrEqual(headingBox!.x + 4)

    await page.screenshot({ path: '../.task/shots/s21-admin-390.png' })
  })
})

test.describe('SC-E5-H8z-03 (d) lista plików datasetu 390', () => {
  test.use({ viewport: { width: 390, height: 844 }, colorScheme: 'light' })

  test('filtry i „Prześlij plik” wyrównane do lewej krawędzi pola wyszukiwania', async ({
    page,
    request,
  }) => {
    await page.goto(`/dataset/files/${await datasetId(request)}`)
    const search = page.getByTestId('files-search')
    const typeFilter = page.getByTestId('files-filter-type')
    const add = page.getByTestId('files-add')
    await expect(search).toBeVisible()
    await expect(typeFilter).toBeVisible()
    await expect(add).toBeVisible()

    const searchBox = await search.boundingBox()
    const typeBox = await typeFilter.boundingBox()
    const addBox = await add.boundingBox()
    expect(searchBox, 'boundingBox pola wyszukiwania').not.toBeNull()
    expect(typeBox, 'boundingBox filtra typu').not.toBeNull()
    expect(addBox, 'boundingBox przycisku przesyłania').not.toBeNull()

    expect(
      Math.abs(typeBox!.x - searchBox!.x),
      `„Typ pliku” (${typeBox!.x}) = „Szukaj plików” (${searchBox!.x}) ± 2 px`,
    ).toBeLessThanOrEqual(2)
    expect(
      Math.abs(addBox!.x - searchBox!.x),
      `„Prześlij plik” (${addBox!.x}) = „Szukaj plików” (${searchBox!.x}) ± 2 px`,
    ).toBeLessThanOrEqual(2)

    await page.screenshot({ path: '../.task/shots/s21-pliki-390.png' })

    // Sprzątanie na końcu ostatniego testu (wzór: s10): lista czatów znowu pusta dla
    // specyfikacji zakładających pusty stan (bez `request` w hooku — patrz nagłówek pliku).
    await deleteAllChats(request, await token(request))
  })
})
