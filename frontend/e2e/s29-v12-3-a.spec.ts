// Scenariusze SC-V12-01, SC-V12-03, SC-V12-04 (work/wp/V12/SCENARIOS.md, brief WP V12-3 T1):
// nazwa klucza API rozpoznawalna na liście, wersja aplikacji na Statusie systemu, dialog usuwania
// bazy z listą powiązań (czaty i wyszukiwarki). Testy pisane PRZED implementacją UI (T2 i T4)
// — mają być czerwone z właściwej przyczyny (brak kolumny nazwy, brak dialogu powiązań).
// Wzorce: s27-e67z2-e (sesja UI, sprzątanie, zrzuty), s09-settings-apikeys (dialog klucza).
import type { APIRequestContext, Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, createDataset, seedCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { createSearch } from './helpers/searches'
import { deleteApiToken, maskToken } from './helpers/settings'
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

const session = uiSession('s29-v12-3-a')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(180_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

// Zasoby do sprzątania po każdym teście (wypełniane przez zasiew i tworzenie przez UI).
const cleanupDatasets: string[] = []
const cleanupChats: string[] = []
const cleanupSearches: string[] = []
const cleanupTokens: string[] = []

test.afterEach(async ({ context, request }) => {
  const token = await adminToken(request)
  for (const id of cleanupChats.splice(0)) {
    await request.delete(`${API_URL}/api/v1/chats`, {
      headers: { authorization: `Bearer ${token}` },
      data: { ids: [id] },
    })
  }
  for (const id of cleanupSearches.splice(0)) {
    await request.delete(`${API_URL}/api/v1/searches/${id}`, {
      headers: { authorization: `Bearer ${token}` },
    })
  }
  for (const id of cleanupDatasets.splice(0)) await deleteDataset(request, token, id)
  for (const key of cleanupTokens.splice(0)) await deleteApiToken(request, token, key)
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

// --- SC-V12-01 ------------------------------------------------------------------------

/** Ustawienia → zakładka „Klucze API” (ścieżka użytkownika z SC-V12-01). */
async function openApiKeys(page: Page): Promise<Locator> {
  await page.goto('/')
  await page.getByRole('navigation').getByRole('link', { name: 'Ustawienia' }).click()
  await page.getByTestId('settings-tab-api').click()
  await expect(page).toHaveURL(/\/user-setting\/api$/)
  const grid = page.getByRole('grid', { name: 'Klucze API' })
  await expect(grid).toBeVisible()
  return grid
}

/**
 * Tworzy klucz API przez UI (opcjonalna nazwa), zamyka dialog z sekretem i zwraca pełny token
 * — potrzebny do sprzątania, bo lista pokazuje tylko maskę.
 */
async function createKeyViaUi(page: Page, name: string | null): Promise<string> {
  await page.getByRole('button', { name: 'Utwórz klucz' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nowy klucz API' })
  await expect(dialog).toBeVisible()
  const nameField = dialog.getByRole('textbox', { name: 'Nazwa (opcjonalna)' })
  if (name !== null) await nameField.fill(name)
  await dialog.getByRole('button', { name: 'Utwórz', exact: true }).click()
  const secret = dialog.getByTestId('settings-new-token')
  await expect(secret).toBeVisible()
  const token = ((await secret.textContent()) ?? '').trim()
  await dialog.getByRole('button', { name: 'Zamknij', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  return token
}

test('SC-V12-01 klucz API po nazwie: wiersz z nazwą i „—”, nazwy po F5, 390 px z title, pole z licznikiem', async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  const grid = await openApiKeys(page)

  // Krok 1: klucz z nazwą — po zamknięciu dialogu wiersz z tą nazwą na liście.
  const named = `Klucz prod z12-${Date.now()}`
  cleanupTokens.push(await createKeyViaUi(page, named))
  await expect(
    grid.getByRole('gridcell').filter({ hasText: named }),
    'wiersz klucza z kolumną Nazwa (dziś: siatka nie ma kolumny Nazwa)',
  ).toBeVisible()
  await shot(page, 'v12-01-keys-1280')

  // Krok 2: klucz bez nazwy — W JEGO WIERSZU kolumna Nazwa pokazuje „—”, nie pustą komórkę
  // (wiersz znajduję po masce tokenu, jedyny tekst wiersza znany przed powstaniem kolumny).
  const unnamedToken = await createKeyViaUi(page, null)
  cleanupTokens.push(unnamedToken)
  await expect(
    grid
      .getByRole('row')
      .filter({ hasText: maskToken(unnamedToken) })
      .getByRole('gridcell', { name: '—', exact: true }),
    'wiersz klucza bez nazwy z „—” (dziś: siatka nie ma kolumny Nazwa)',
  ).toBeVisible()

  // Krok 3: F5 — nazwy zostają (z serwera, nie ze stanu przeglądarki).
  await page.reload()
  await expect(
    page.getByRole('grid', { name: 'Klucze API' }).getByRole('gridcell').filter({ hasText: named }),
  ).toBeVisible()

  // Wariant 390 px: nazwa skracana wielokropkiem, pełna nazwa w atrybucie title.
  await page.setViewportSize(MOBILE)
  await expect(
    page.getByRole('grid', { name: 'Klucze API' }).getByRole('gridcell').filter({ hasText: named }),
  ).toHaveAttribute('title', named)

  // Pole nazwy: maksimum 128 znaków i licznik (np. „0/128”).
  await page.getByRole('button', { name: 'Utwórz klucz' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nowy klucz API' })
  await expect(dialog).toBeVisible()
  const nameField = dialog.getByRole('textbox', { name: 'Nazwa (opcjonalna)' })
  await expect(nameField).toHaveAttribute('maxLength', '128')
  await expect(dialog.getByText('0/128')).toBeVisible()
  await dialog.getByRole('button', { name: 'Zamknij', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await shot(page, 'v12-01-keys-390')
  await expectNoLayoutDefects(page, 'SC-V12-01 klucze API 390')
})

// --- SC-V12-03 ------------------------------------------------------------------------

test('SC-V12-03 status: karta wersji zawiera aktualną wersję (1.3.0), nie „0.0.0”', async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP)
  // Administracja → Status systemu (ścieżka użytkownika).
  await page.goto('/')
  await page.getByRole('navigation').getByRole('link', { name: 'Administracja' }).click()
  await expect(page).toHaveURL(/\/admin\/users$/)
  await page.getByTestId('admin-tab-status').click()
  const card = page.getByTestId('admin-status-version')
  await expect(card).toBeVisible()
  await shot(page, 'v12-03-status-1280')
  await expect(card, 'karta wersji pokazuje 1.3.0 (K20 §3)').toContainText('1.3.0')
  await expect(card).not.toContainText('0.0.0')
  await expectNoLayoutDefects(page, 'SC-V12-03 status systemu')
})

// --- SC-V12-04 ------------------------------------------------------------------------

test.describe('SC-V12-04 usuwanie bazy z listą powiązań', () => {
  type Seed = { datasetId: string; chatNames: string[]; searchNames: string[] }

  /**
   * Zasiew przez API: baza podpięta do czatów i wyszukiwarek (wiązania `chat_datasets` /
   * `search_datasets`, jak je tworzy UI). Czat wymaga bazy ze SPARSOWANYM dokumentem
   * („The dataset … doesn't own parsed file”, kod 102), więc baza powstaje przez `seedCorpus`
   * (upload + parse + oczekiwanie na DONE). Nazwy czatów/wyszukiwarek wracają do asercji.
   */
  async function seedUsage(
    request: APIRequestContext,
    token: string,
    datasetName: string,
    chatNames: string[],
    searchNames: string[],
  ): Promise<Seed> {
    const corpus = await seedCorpus(request, token, {
      datasetName,
      documentName: `${datasetName}.txt`,
      documentBody: 'Treść dokumentu na potrzeby powiązań bazy (SC-V12-04).',
    })
    cleanupDatasets.push(corpus.datasetId)
    for (const name of chatNames) {
      cleanupChats.push(await createChat(request, token, { name, datasetIds: [corpus.datasetId] }))
    }
    for (const name of searchNames) {
      cleanupSearches.push(
        await createSearch(request, token, { name, datasetIds: [corpus.datasetId] }),
      )
    }
    return { datasetId: corpus.datasetId, chatNames, searchNames }
  }

  /** Bazy wiedzy → ⋮ przy bazie → „Usuń”; zwraca dialog usuwania (`delete-dataset-dialog`). */
  async function openDeleteDialog(page: Page, datasetName: string): Promise<Locator> {
    await page.goto('/datasets')
    await page.getByRole('button', { name: `Menu bazy wiedzy ${datasetName}` }).click()
    await page.getByRole('menuitem', { name: 'Usuń' }).click()
    const dialog = page.getByTestId('delete-dataset-dialog')
    await expect(dialog, 'dialog usuwania z listą powiązań (T4)').toBeVisible()
    return dialog
  }

  test('dialog pokazuje 2 czaty i 1 wyszukiwarkę; „Usuń mimo to” usuwa bazę', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ts = Date.now()
    const datasetName = `V12-4 GUS z12-${ts}`
    const chatNames = [`Czat GUS z12-${ts}`, `Czat Wawel z12-${ts}`]
    const searchNames = [`Wyszukiwarka GUS z12-${ts}`]
    const seed = await seedUsage(request, token, datasetName, chatNames, searchNames)

    await page.setViewportSize(DESKTOP)
    const dialog = await openDeleteDialog(page, datasetName)
    await expect(dialog.getByTestId('delete-dataset-usage')).toBeVisible()
    await expect(dialog.getByTestId('delete-dataset-usage-chats')).toContainText(chatNames[0]!)
    await expect(dialog.getByTestId('delete-dataset-usage-chats')).toContainText(chatNames[1]!)
    await expect(dialog.getByTestId('delete-dataset-usage-searches')).toContainText(searchNames[0]!)
    // T8: lista mieszcząca się bez przewijania (2 pozycje) — podpowiedź przewijania nie istnieje.
    await expect(dialog.getByTestId('delete-dataset-usage-scrollhint')).toHaveCount(0)
    await shot(page, 'v12-04-dialog-1280')
    const confirm = dialog.getByTestId('delete-dataset-confirm')
    await expect(confirm).toHaveText('Usuń mimo to')
    // T5: potwierdzenie wyraźnie czerwone (motyw szarzeje text-Button) — tło z dominującym
    // kanałem czerwonym (R > G+40 i R > B+40); „czerwony przed poprawką” = padający test.
    const confirmBg = await confirm.evaluate((element) => getComputedStyle(element).backgroundColor)
    const [r = 0, g = 0, b = 0] = confirmBg.match(/\d+(\.\d+)?/g)?.map(Number) ?? []
    expect(
      r,
      `tło „Usuń mimo to” ma dominujący kanał czerwony (R > G+40; tło: ${confirmBg})`,
    ).toBeGreaterThan(g + 40)
    expect(
      r,
      `tło „Usuń mimo to” ma dominujący kanał czerwony (R > B+40; tło: ${confirmBg})`,
    ).toBeGreaterThan(b + 40)
    await confirm.click()
    // Baza znika z listy.
    await expect(page.getByRole('button', { name: `Menu bazy wiedzy ${datasetName}` })).toHaveCount(
      0,
    )
    // Usunięta przez UI — ze sprzątania afterEach wyłączona (powtórne DELETE na nieistniejącej
    // bazie zwraca kopertę odmowy i zabiłoby test przy zielonym dialogu).
    cleanupDatasets.splice(cleanupDatasets.indexOf(seed.datasetId), 1)
    await shot(page, 'v12-04-after-delete-1280')
    await expectNoLayoutDefects(page, 'SC-V12-04 dialog powiązań 1280')
  })

  test('baza bez powiązań — dialog bez sekcji powiązań, przycisk „Usuń”', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const datasetName = `V12-4 pusta z12-${Date.now()}`
    cleanupDatasets.push(await createDataset(request, token, datasetName))

    await page.setViewportSize(DESKTOP)
    const dialog = await openDeleteDialog(page, datasetName)
    await expect(dialog.getByTestId('delete-dataset-usage')).toHaveCount(0)
    const confirm = dialog.getByTestId('delete-dataset-confirm')
    await expect(confirm).toHaveText('Usuń')
    await shot(page, 'v12-04-empty-1280')
    await expectNoLayoutDefects(page, 'SC-V12-04 dialog bez powiązań')
  })

  test('lista 7 czatów — kontener przewijany, wysokość ≤ 40 % viewportu', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ts = Date.now()
    const datasetName = `V12-4 dużo z12-${ts}`
    // Długie nazwy zawijają się (SC-V12-04 krok 2), więc 7 pozycji przepełnia 40vh i wymusza
    // przewijanie — krótkie nazwy mieszkałyby się bez przewijacza.
    const base = 'Czat zespołu z długą nazwą — sprawdzenie zawijania i przewijania listy. '
    const chatNames = Array.from(
      { length: 7 },
      (_, index) => `${base.repeat(2)}(#${index + 1}, z12-${ts})`,
    )
    await seedUsage(request, token, datasetName, chatNames, [])

    await page.setViewportSize(DESKTOP)
    const dialog = await openDeleteDialog(page, datasetName)
    const chats = dialog.getByTestId('delete-dataset-usage-chats')
    await expect(chats).toBeVisible()
    const scrolled = await chats.evaluate((element) => ({
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
      height: element.getBoundingClientRect().height,
    }))
    expect(scrolled.scrollHeight, 'lista 7 czatów ma przewijacz').toBeGreaterThan(
      scrolled.clientHeight,
    )
    expect(scrolled.height, 'wysokość listy ≤ 40 % wysokości viewportu').toBeLessThanOrEqual(
      (page.viewportSize()?.height ?? 0) * 0.4 + 1,
    )
    // T6 (QA V12-3-1, MAJOR wizualny): pozycje odróżnialne — separator i punktor na `li` —
    // oraz kontener w ramce. T8 (review T6, MAJOR): sygnał przewijania niezależny od motywu —
    // zamiast gradientowych maski w kolorze tła (ciemny pas w ciemnym motywie) podpowiedź
    // tekstowa pod listą, widoczna tylko gdy lista się nie mieści.
    const itemStyle = await chats
      .locator('li')
      .first()
      .evaluate((element) => {
        const style = getComputedStyle(element)
        return { borderBottomWidth: style.borderBottomWidth, listStyleType: style.listStyleType }
      })
    expect(itemStyle.borderBottomWidth, 'pozycja ma separator (border-bottom)').not.toBe('0px')
    expect(itemStyle.listStyleType, 'pozycja ma punktor').not.toBe('none')
    const listFrame = await chats.evaluate((element) => getComputedStyle(element).borderTopWidth)
    expect(listFrame, 'lista powiązań w ramce (border-top)').not.toBe('0px')
    await expect(
      dialog.getByTestId('delete-dataset-usage-scrollhint'),
      'podpowiedź przewijania widoczna (lista 7 czatów się nie mieści)',
    ).toBeVisible()
    await shot(page, 'v12-04-scroll-1280')
    await expect(dialog.getByTestId('delete-dataset-confirm')).toHaveText('Usuń mimo to')
    await expectNoLayoutDefects(page, 'SC-V12-04 lista 7 czatów')
  })

  test('390 px — dialog z powiązaniami mieści się i usuwa bazę', async ({ page, request }) => {
    const token = await adminToken(request)
    const ts = Date.now()
    const datasetName = `V12-4 mobilny z12-${ts}`
    const chatNames = [`Czat GUS z12-${ts}`, `Czat Wawel z12-${ts}`]
    const searchNames = [`Wyszukiwarka GUS z12-${ts}`]
    const seed = await seedUsage(request, token, datasetName, chatNames, searchNames)

    await page.setViewportSize(MOBILE)
    const dialog = await openDeleteDialog(page, datasetName)
    await expect(dialog.getByTestId('delete-dataset-usage-chats')).toContainText(chatNames[0]!)
    await expect(dialog.getByTestId('delete-dataset-usage-searches')).toContainText(searchNames[0]!)
    await shot(page, 'v12-04-dialog-390')
    const confirm = dialog.getByTestId('delete-dataset-confirm')
    await expect(confirm).toHaveText('Usuń mimo to')
    await confirm.click()
    await expect(page.getByRole('button', { name: `Menu bazy wiedzy ${datasetName}` })).toHaveCount(
      0,
    )
    // Usunięta przez UI — ze sprzątania afterEach wyłączona (jak w teście 1280).
    cleanupDatasets.splice(cleanupDatasets.indexOf(seed.datasetId), 1)
    await expectNoLayoutDefects(page, 'SC-V12-04 dialog powiązań 390')
  })

  test('błąd trasy usage — „Nie udało się sprawdzić powiązań”, aktywny „Usuń”', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ts = Date.now()
    const datasetName = `V12-4 błąd z12-${ts}`
    await seedUsage(request, token, datasetName, [`Czat GUS z12-${ts}`], [])

    // Trasa usage zwraca 500 — dialog ma działać jak dziś plus czytelny komunikat.
    // Syntetyczny Response (łatka fetch w stronie, przed skryptami aplikacji), NIE `page.route`:
    // odpowiedź 500 z sieci Chromium loguje jako błąd konsoli („Failed to load resource”), który
    // strażnik fixture'a traktuje jako porażkę testu — błąd ma być ZAPROJEKTOWANY, nie zgłoszony.
    await page.addInitScript(() => {
      const original = window.fetch.bind(window)
      window.fetch = async (input, init) => {
        const url =
          typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
        if (url.includes('/api/wd/v1/datasets/') && url.endsWith('/usage')) {
          return new Response(JSON.stringify({ error: { code: 'internal', message: 'boom' } }), {
            status: 500,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        return original(input, init)
      }
    })
    await page.setViewportSize(DESKTOP)
    const dialog = await openDeleteDialog(page, datasetName)
    await expect(dialog.getByTestId('delete-dataset-usage-error')).toContainText(
      'Nie udało się sprawdzić powiązań',
    )
    const confirm = dialog.getByTestId('delete-dataset-confirm')
    await expect(confirm).toHaveText('Usuń')
    await expect(confirm).toBeEnabled()
    await shot(page, 'v12-04-error-1280')
    await expectNoLayoutDefects(page, 'SC-V12-04 błąd usage')
  })
})
