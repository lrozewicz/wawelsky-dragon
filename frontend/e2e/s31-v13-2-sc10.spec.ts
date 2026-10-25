// SC-V13-10 (work/wp/V13/SCENARIOS.md, brief V13-2 T1a): tworzę czat i od razu wybieram bazę.
// Testy pisane PRZED implementacją (T2) — mają być CZERWONE z właściwej przyczyny: brak pola
// „Bazy wiedzy (opcjonalnie)” w oknie „Nowy czat”, brak dopisku „brak przetworzonych plików”,
// brak wysyłania `dataset_ids` z okna tworzenia. Kroki k1–k5 + warianty (390 px, ciemny, EN,
// podwójny klik „Utwórz” → jeden czat z wybraną bazą, liczba czatów przez API).
// Wzorce: s30-v12z-qa.spec.ts (sesja/sprzątanie), s07-chat-citations.spec.ts (pytanie
// z cytowaniem na seedCorpus), s07a-chats-list.spec.ts (okno „Utwórz czat”).
import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createDataset, seedCorpus } from './helpers'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const SHOTS = process.env.WD_SHOTS_DIR ?? ''

const session = uiSession('s31-v13-2-sc10')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(180_000)

const VIEWPORT_WIDE = { width: 1280, height: 800 }
const VIEWPORT_NARROW = { width: 390, height: 844 }

/** Unikalny sufiks nazw zasobów (wzór s30). */
function uniq(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`
}

/** Nazwa bazy w wyrażeniu regularnym — dostępna nazwa opcji może zawierać dopiski. */
function nameRe(name: string): RegExp {
  return new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
}

/** Pole „Bazy wiedzy (opcjonalnie)” okna tworzenia (makieta SC-V13-10; CONTRACT §4). */
function datasetsField(dialog: Locator): Locator {
  return dialog.getByRole('combobox', { name: 'Bazy wiedzy (opcjonalnie)' })
}

/** Chip z nazwą bazy w polu Autocomplete okna tworzenia. */
function chipLabel(dialog: Locator): Locator {
  return dialog.locator('.MuiAutocomplete-root').locator('.MuiChip-label')
}

const QUESTION = 'Gdzie mieszkał smok wawelski i kto go pokonał?'
// Treść dokumentu z s07 (pytanie trafia w chunk retrieval-em; fake-llm odpowiada „Na podstawie
// źródeł: … [ID:n]”, co daje chip cytowania).
const DOCUMENT_BODY = [
  'Wawelski smok mieszkał w jamie pod Wawelem, a pokonał go szewc Skuba. Mieszkańcy Krakowa',
  'bali się smoka wawelskiego, który porywał owce i bydło z pastwisk wokół Wawelu, więc król',
  'obiecał nagrodę temu, kto uwolni miasto od smoka. Wielu śmiałków próbowało zmierzyć się ze',
  'smokiem wawelskim, ale żaden nie wrócił z jamy pod wzgórzem. Dopiero szewc Skuba wpadł na',
  'pomysł, by podrzucić smokowi barana wypełnionego siarką i smołą. Smok wawelski połknął',
  'przynętę, poczuł piekące pragnienie i pobiegł nad Wisłę, gdzie pił wodę tak długo, aż pękł.',
  'Od tego czasu miasto żyło w spokoju, a na pamiątkę zwycięstwa nad smokiem wawelskim',
  'postawiono pod Wawelem rzeźbę smoka, która do dziś zieje ogniem ku uciesze turystów',
  'i mieszkańców Krakowa. Legenda o smoku wawelskim należy do najstarszych podań o Krakowie',
  'i do dziś opowiada się ją dzieciom w przedszkolach i szkołach. Przewodnicy na Wawelu pokazują',
  'turystom jamę smoka i opowiadają, jak dzielny szewc Skuba pokonał smoka wawelskiego',
  'podstępem, a nie siłą. KONIEC-FRAGMENTU-SMOKA.',
].join(' ')

// Dwie bazy z przetworzonymi plikami + baza pusta (makieta SC-V13-10: GUS · Mix · „Pusta baza”).
let token = ''
let gusId = ''
let gusName = ''
let mixName = ''
let pustaName = ''
const chatIds: string[] = []
const datasetIds: string[] = []

test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

test.afterEach(async ({ context }) => {
  // Rotacja cookie `wd_refresh` (C9): kolejny test startuje ze ŚWIEŻYM stanem sesji.
  await session.save(context)
})

test.beforeAll(async ({ request }) => {
  test.setTimeout(240_000)
  token = await apiLogin(request)
  gusName = `E2E S31 GUS ${uniq()}`
  const gus = await seedCorpus(request, token, {
    datasetName: gusName,
    documentName: 'e2e-s31-gus.txt',
    documentBody: DOCUMENT_BODY,
  })
  gusId = gus.datasetId
  datasetIds.push(gus.datasetId)
  mixName = `E2E S31 Mix ${uniq()}`
  const mix = await seedCorpus(request, token, {
    datasetName: mixName,
    documentName: 'e2e-s31-mix.txt',
    documentBody: `Notatka służbowa dla scenariusza SC-V13-10: ${uniq()} — treść do parsowania.`,
  })
  datasetIds.push(mix.datasetId)
  pustaName = `E2E S31 Pusta baza ${uniq()}`
  datasetIds.push(await createDataset(request, token, pustaName))
})

test.afterAll(async ({ request }) => {
  if (token === '') return
  const headers = { authorization: `Bearer ${token}` }
  if (chatIds.length > 0) {
    await request.delete(`${process.env.WD_E2E_API_URL}/api/v1/chats`, {
      headers,
      data: { ids: chatIds },
    })
  }
  for (const id of datasetIds) {
    await request.delete(`${process.env.WD_E2E_API_URL}/api/v1/datasets/${id}`, { headers })
  }
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Id czatu z adresu `/chat/:id` po utworzeniu — do sprzątania i sprawdzeń przez API. */
function chatIdFromUrl(page: Page): string {
  const id = page.url().match(/\/chat\/([^/?]+)/)?.[1]
  expect(id, 'adres obszaru czatu zawiera id').toBeDefined()
  return id as string
}

/** Otwiera okno „Nowy czat” z listy `/chats` (pusty stan albo przycisk w nagłówku). */
async function openCreateDialog(page: Page): Promise<Locator> {
  await page.goto('/chats')
  await page.getByRole('button', { name: 'Utwórz czat' }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  return dialog
}

test('SC-V13-10 k1: okno „Nowy czat” — pole „Bazy wiedzy (opcjonalnie)”, fokus w „Nazwa”, walidacja pustej nazwy', async ({
  page,
}) => {
  await page.setViewportSize(VIEWPORT_WIDE)
  const dialog = await openCreateDialog(page)
  // Fokus w „Nazwa” (U11, jak dziś).
  await expect(page.getByLabel('Nazwa')).toBeFocused()
  // Makieta SC-V13-10: okno ma POLE WYBORU BAZ — dziś go nie ma (czerwień = brak funkcji).
  await expect(datasetsField(dialog)).toBeVisible()
  // Teksty pomocnicze z CONTRACT §4.
  await expect(dialog.getByText('Bez bazy czat odpowiada tylko z wiedzy modelu.')).toBeVisible()
  await expect(dialog.getByText('Bazy możesz zmienić później w ustawieniach czatu.')).toBeVisible()
  await shot(page, 's31-sc10-k1-1280')
  // Walidacja U11 (istniejące zachowanie, k1): klik „Utwórz” bez nazwy → komunikat pod polem + fokus.
  await dialog.getByRole('button', { name: 'Utwórz', exact: true }).click()
  await expect(page.getByText('Pole wymagane')).toBeVisible()
  await expect(page.getByLabel('Nazwa')).toBeFocused()
  await expectNoLayoutDefects(page, 'SC-V13-10 k1: okno „Nowy czat” z komunikatem walidacji')
})

test('SC-V13-10 k2: wybór „GUS” → chip; „Pusta baza” nieaktywna z dopiskiem „brak przetworzonych plików”', async ({
  page,
}) => {
  await page.setViewportSize(VIEWPORT_WIDE)
  const dialog = await openCreateDialog(page)
  await dialog.getByLabel('Nazwa').fill(`E2E S31 czat k2 ${uniq()}`)
  await expect(datasetsField(dialog)).toBeVisible() // czerwień: brak funkcji

  await datasetsField(dialog).click()
  // „Pusta baza” na liście: wyszarzona i z widocznym dopiskiem (makieta, BACKLOG §C.14b).
  const emptyOption = page.getByRole('option', { name: nameRe(pustaName) })
  await expect(emptyOption).toBeVisible()
  await expect(emptyOption).toHaveAttribute('aria-disabled', 'true')
  await expect(emptyOption).toContainText('brak przetworzonych plików')
  // Druga baza z przetworzonymi plikami pozostaje wybieralna.
  await expect(page.getByRole('option', { name: nameRe(mixName) })).not.toHaveAttribute(
    'aria-disabled',
    'true',
  )
  await shot(page, 's31-sc10-k2-1280')
  await page.getByRole('option', { name: nameRe(gusName) }).click()
  // Chip z nazwą wybranej bazy w polu (Autocomplete multiple).
  await expect(chipLabel(dialog)).toHaveText(gusName)
  // Wybór zamyka listę (QA MAJOR-1): „Utwórz” klikalny bez Escape — asercja zamiast zamykania.
  await expect(page.getByRole('listbox')).toBeHidden()
  await expectNoLayoutDefects(page, 'SC-V13-10 k2: okno z wybranym chipem i listą z dopiskiem')
})

/** Niezmiennik QA V13-z-1 W1: w spoczynku żadna opcja nie jest widoczna CZĘŚCIOWO —
 * każda jest albo cała w liście, albo w całości pod dolną krawędzią (przewinięta). */
async function expectNoPartialOption(listbox: Locator): Promise<void> {
  const geometry = await listbox.evaluate((list) => {
    const listBox = list.getBoundingClientRect()
    return {
      listTop: listBox.top,
      listBottom: listBox.bottom,
      options: Array.from(list.querySelectorAll<HTMLLIElement>('[role="option"]')).map((option) => {
        const rect = option.getBoundingClientRect()
        return { name: option.textContent ?? '', top: rect.top, bottom: rect.bottom }
      }),
    }
  })
  for (const option of geometry.options) {
    expect(option.top, `górna krawędź „${option.name}” w liście`).toBeGreaterThanOrEqual(
      geometry.listTop - 0.5,
    )
    const wholeOrScrolled =
      option.bottom <= geometry.listBottom + 0.5 || option.top >= geometry.listBottom - 0.5
    expect(
      wholeOrScrolled,
      `opcja „${option.name}” cała w liście albo w całości przewinięta (${option.top}…${option.bottom} vs dół ${geometry.listBottom})`,
    ).toBe(true)
  }
}

test('SC-V13-10 k2b (QA V13-z-1 W1): lista przy 3 bazach — żadna opcja nie jest przycięta', async ({
  page,
}) => {
  await page.setViewportSize(VIEWPORT_WIDE)
  const dialog = await openCreateDialog(page)
  const listbox = page.getByRole('listbox')
  await datasetsField(dialog).click()
  await expect(listbox).toBeVisible()
  // Trzy bazy z beforeAll (GUS · Mix · „Pusta baza”) — warunek z QA W1 (wada widać już przy 3).
  // Bez sztywnego licznika: ponowienie testu w NOWYM workerze odpala `beforeAll` drugi raz
  // (3 + 3 baz), a istota asercji jest w geometrii poniżej, nie w liczbie pozycji.
  await expect(listbox.getByRole('option').first()).toBeVisible()
  expect(
    await listbox.getByRole('option').count(),
    'lista zawiera co najmniej trzy bazy',
  ).toBeGreaterThanOrEqual(3)
  // Stan spoczynku: koniec animacji poppera (Grow skalował prostokąty przy pomiarze).
  await expect
    .poll(() =>
      page.evaluate(() => document.getAnimations().filter((a) => a.playState === 'running').length),
    )
    .toBe(0)
  // Pomiary (QA W1): „GUS” był przycięty w połowie wysokości przy dolnej krawędzi listy.
  await expectNoPartialOption(listbox)
  // QA V13-z-2 D4: pełna nazwa bazy w `title` opcji — wielokropek nie zjada informacji.
  for (const name of [gusName, mixName, pustaName]) {
    await expect(listbox.getByRole('option', { name: nameRe(name) })).toHaveAttribute('title', name)
  }
  await shot(page, 's31-sc10-k2b-1280')
})

test('SC-V13-10 k3: „Utwórz” z bazą — obszar czatu, pytanie z cytowaniem, baza zaznaczona w ustawieniach', async ({
  page,
}) => {
  await page.setViewportSize(VIEWPORT_WIDE)
  const chatName = `E2E S31 czat k3 ${uniq()}`
  const dialog = await openCreateDialog(page)
  await dialog.getByLabel('Nazwa').fill(chatName)
  await expect(datasetsField(dialog)).toBeVisible() // czerwień: brak funkcji
  await datasetsField(dialog).click()
  await page.getByRole('option', { name: nameRe(gusName) }).click()
  await expect(chipLabel(dialog)).toHaveText(gusName)
  // Wybór zamyka listę (QA MAJOR-1) — „Utwórz” klikalny BEZ Escape.
  await expect(page.getByRole('listbox')).toBeHidden()
  await dialog.getByRole('button', { name: 'Utwórz', exact: true }).click()
  await expect(page).toHaveURL(/\/chat\/[^/]+$/)
  chatIds.push(chatIdFromUrl(page))
  await expect(page.getByRole('heading', { name: chatName })).toBeVisible()

  // Pierwsze pytanie korzysta z bazy (fake-llm: „Na podstawie źródeł…” + chip cytowania).
  await page.getByPlaceholder('Wpisz pytanie…').fill(QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()
  const answer = page.getByTestId('message-assistant').last()
  await expect(answer).toContainText('Na podstawie źródeł', { timeout: 30_000 })
  await expect(page.getByRole('button', { name: 'Cytowanie 1' })).toBeVisible()

  // Ustawienia czatu → zakładka „Asystent” → baza „GUS” zaznaczona.
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  const drawer = page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia czatu' })
  await expect(drawer).toBeVisible()
  await expect(drawer.locator('.MuiAutocomplete-root').getByText(gusName)).toBeVisible()
  await page.keyboard.press('Escape')
  // Koniec animacji zamykania szuflady przed pomiarem: strażnik układu na końcu testu łapał
  // szufladę w trakcie wysuwania (stan przejściowy „poza oknem”, nie wada ekranu).
  await expect(drawer).toBeHidden()
  await expectNoLayoutDefects(page, 'SC-V13-10 k3: obszar czatu z cytowaniem po utworzeniu z bazą')
})

test('SC-V13-10 k4: czat bez bazy działa (odpowiedź bez cytowania, bez ostrzeżeń blokujących)', async ({
  page,
}) => {
  await page.setViewportSize(VIEWPORT_WIDE)
  const chatName = `E2E S31 czat k4 ${uniq()}`
  const dialog = await openCreateDialog(page)
  // To samo okno co w k1 — pole baz obecne także przy tworzeniu bez wyboru.
  await expect(datasetsField(dialog)).toBeVisible() // czerwień: brak funkcji
  await dialog.getByLabel('Nazwa').fill(chatName)
  await dialog.getByRole('button', { name: 'Utwórz', exact: true }).click()
  await expect(page).toHaveURL(/\/chat\/[^/]+$/)
  chatIds.push(chatIdFromUrl(page))

  await page.getByPlaceholder('Wpisz pytanie…').fill('Jaki jest obecny rok testowy?')
  await page.getByRole('button', { name: 'Wyślij' }).click()
  const answer = page.getByTestId('message-assistant').last()
  // Bez bazy fake-llm odpowiada „Odpowiedź testowa: …” — czat działa, bez cytowań.
  await expect(answer).toContainText('Odpowiedź testowa', { timeout: 30_000 })
  await expect(page.getByRole('button', { name: /^Cytowanie/ })).toHaveCount(0)
  await expectNoLayoutDefects(page, 'SC-V13-10 k4: czat bez bazy po pytaniu')
})

test('SC-V13-10 k5: wejście `/chats?isCreate=true` otwiera to samo okno', async ({ page }) => {
  await page.setViewportSize(VIEWPORT_WIDE)
  await page.goto('/chats?isCreate=true')
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(page.getByLabel('Nazwa')).toBeFocused()
  await expect(datasetsField(dialog)).toBeVisible() // czerwień: brak funkcji
  await expectNoLayoutDefects(page, 'SC-V13-10 k5: okno z parametru isCreate')
})

test('SC-V13-10 wariant 390: okno dopasowane do treści, nie pełnoekranowe (U12)', async ({
  page,
}) => {
  await page.setViewportSize(VIEWPORT_NARROW)
  const dialog = await openCreateDialog(page)
  await expect(datasetsField(dialog)).toBeVisible() // czerwień: brak funkcji
  // Krótkie dialogi na telefonie nie są pełnoekranowe (CONTRACT §2: „KRÓTKIE”).
  const classes = (await dialog.getAttribute('class')) ?? ''
  expect(classes, 'klasy paper okna').not.toContain('MuiDialog-paperFullScreen')
  const box = await dialog.boundingBox()
  expect(box, 'wymiary okna').not.toBeNull()
  expect(box!.x, 'margines lewy ≥ 16 px').toBeGreaterThanOrEqual(16)
  expect(
    VIEWPORT_NARROW.width - (box!.x + box!.width),
    'margines prawy ≥ 16 px',
  ).toBeGreaterThanOrEqual(16)
  expect(box!.y, 'górna krawędź w oknie').toBeGreaterThanOrEqual(0)
  expect(box!.y + box!.height, 'dolna krawędź w oknie').toBeLessThanOrEqual(VIEWPORT_NARROW.height)
  await shot(page, 's31-sc10-390')
  await expectNoLayoutDefects(page, 'SC-V13-10 wariant 390: okno „Nowy czat”')
})

test.describe('SC-V13-10 wariant ciemny', () => {
  test.use({ colorScheme: 'dark' })

  test('okno „Nowy czat” czytelne w ciemnym motywie', async ({ page }) => {
    await page.setViewportSize(VIEWPORT_WIDE)
    const dialog = await openCreateDialog(page)
    await expect(datasetsField(dialog)).toBeVisible() // czerwień: brak funkcji
    await shot(page, 's31-sc10-dark')
    await expectNoLayoutDefects(page, 'SC-V13-10 wariant ciemny: okno „Nowy czat”')
  })
})

test('SC-V13-10 wariant EN: okno tworzenia po angielsku', async ({ page, request }) => {
  await setProfileLanguage(request, token, 'en')
  try {
    await page.setViewportSize(VIEWPORT_WIDE)
    await page.goto('/chats')
    await page.getByRole('button', { name: 'Create chat' }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(page.getByLabel('Name')).toBeFocused()
    // EN etykieta nowego pola (odpowiednik `chats.datasetsOptional`); lista po angielsku.
    const field = dialog.getByRole('combobox', { name: /knowledge bases/i })
    await expect(field).toBeVisible() // czerwień: brak funkcji
    await field.click()
    await expect(page.getByRole('option', { name: nameRe(pustaName) })).toBeVisible()
    await expect(page.getByRole('option', { name: nameRe(pustaName) })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    await shot(page, 's31-sc10-en')
    // Zamknięcie listy przed pomiarem (opcje poza dialogiem — U4); czekamy na koniec animacji
    // zwijania — stan przejściowy dawał fałszywy „covered” (etykieta nad polem w trakcie blur).
    await page.keyboard.press('Escape')
    await expect(page.getByRole('listbox')).toBeHidden()
    // Escape domyka listę, a Autocomplete zwraca fokus na pole — etykieta przechodzi wtedy dwie
    // animacje (opad przy blur, ponowne uniesienie po zwrocie fokusu). Pomiar w ich trakcie
    // widział etykietę na środku pola: fałszywy „covered: input … label „Knowledge bases
    // (optional)”” (czerwień verify-full T7). Mierzymy dopiero po ustaniu animacji okna.
    await expect
      .poll(
        () =>
          dialog.evaluate(
            (el) =>
              el
                .getAnimations({ subtree: true })
                .filter((animation) => animation.playState === 'running').length,
          ),
        { timeout: 5_000 },
      )
      .toBe(0)
    await expectNoLayoutDefects(page, 'SC-V13-10 wariant EN: okno tworzenia z listą baz')
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})

test('SC-V13-10 wariant: podwójny klik „Utwórz” → jeden czat (liczba czatów przez API)', async ({
  page,
  request,
}) => {
  await page.setViewportSize(VIEWPORT_WIDE)
  const chatName = `E2E S31 czat podwójny ${uniq()}`
  const dialog = await openCreateDialog(page)
  await dialog.getByLabel('Nazwa').fill(chatName)
  await expect(datasetsField(dialog)).toBeVisible() // czerwień: brak funkcji
  await datasetsField(dialog).click()
  await page.getByRole('option', { name: nameRe(gusName) }).click()
  await expect(chipLabel(dialog)).toHaveText(gusName)
  // Wybór zamyka listę (QA MAJOR-1) — podwójny klik trafia w „Utwórz” bez zamykania listy.
  await expect(page.getByRole('listbox')).toBeHidden()
  await dialog.getByRole('button', { name: 'Utwórz', exact: true }).dblclick()
  await expect(page).toHaveURL(/\/chat\/[^/]+$/)
  chatIds.push(chatIdFromUrl(page))

  // Liczba czatów o tej nazwie przez API: dokładnie jeden (U7 — akcja nie dubluje się).
  const headers = { authorization: `Bearer ${token}` }
  const listed = await request.get(`${process.env.WD_E2E_API_URL}/api/v1/chats`, { headers })
  const body = (await listed.json()) as { data: { chats: { id: string; name: string }[] } }
  const mine = body.data.chats.filter((chat) => chat.name === chatName)
  expect(mine, 'czaty o nazwie z podwójnego kliknięcia').toHaveLength(1)

  // Czat z podwójnego kliknięcia ma wybraną bazę „GUS” (dataset_ids przez API).
  const detail = await request.get(
    `${process.env.WD_E2E_API_URL}/api/v1/chats/${mine[0]?.id ?? ''}`,
    {
      headers,
    },
  )
  const detailBody = (await detail.json()) as { data: { dataset_ids: string[] } }
  expect(detailBody.data.dataset_ids, 'baza wybrana w oknie tworzenia').toContain(gusId)
  await expectNoLayoutDefects(page, 'SC-V13-10 podwójny klik: obszar czatu po utworzeniu')
})

test('SC-V13-10 wariant 31 baz: lista nie zasłania „Utwórz”, po wyborze zamyka się (QA MAJOR-1)', async ({
  page,
  request,
}) => {
  // 28 wypełniaczy → 31 baz w liście (odtworzenie warunków QA V13-2-1: wada widać od ~5 pozycji).
  for (let i = 0; i < 28; i += 1) {
    datasetIds.push(await createDataset(request, token, `E2E S31 wypełniacz ${i + 1} ${uniq()}`))
  }
  await page.setViewportSize(VIEWPORT_WIDE)
  const dialog = await openCreateDialog(page)
  await dialog.getByLabel('Nazwa').fill(`E2E S31 czat 31baz ${uniq()}`)

  const listbox = page.getByRole('listbox')
  await datasetsField(dialog).click()
  await expect(listbox).toBeVisible()
  const optionCount = await listbox.getByRole('option').count()
  expect(optionCount, 'lista zawiera ≥ 31 pozycji').toBeGreaterThanOrEqual(31)

  // Lista ZAWSZE mieści się nad stopką z przyciskami (1280×800 i 390×844).
  const actions = dialog.locator('.MuiDialogActions-root')
  const noOverlap = async (label: string) => {
    const listBox = await listbox.boundingBox()
    const actionsBox = await actions.boundingBox()
    expect(listBox, `prostokąt listy (${label})`).not.toBeNull()
    expect(actionsBox, `prostokąt stopki (${label})`).not.toBeNull()
    expect(listBox!.y + listBox!.height, `lista nad stopką (${label})`).toBeLessThanOrEqual(
      actionsBox!.y + 1,
    )
  }

  await noOverlap('1280')
  // Lista przewijana (31 pozycji): w spoczynku nadal żadna opcja nie jest ucięta (QA W1).
  await expectNoPartialOption(listbox)
  // „Utwórz” klikalny przy otwartej liście: elementFromPoint w centrum trafia w przycisk.
  const create = dialog.getByRole('button', { name: 'Utwórz', exact: true })
  const createBox = await create.boundingBox()
  expect(createBox, 'prostokąt „Utwórz”').not.toBeNull()
  const hit = await page.evaluate(
    ({ cx, cy }: { cx: number; cy: number }) => {
      const element = document.elementFromPoint(cx, cy)
      return element === null ? '' : (element.closest('button')?.textContent ?? element.tagName)
    },
    {
      cx: createBox!.x + createBox!.width / 2,
      cy: createBox!.y + createBox!.height / 2,
    },
  )
  expect(hit, 'elementFromPoint w centrum „Utwórz”').toBe('Utwórz')
  await shot(page, 's31-sc10-31baz-1280-list-open')

  // Wybór zamyka listę — „Utwórz” klikalny BEZ Escape (GUS na końcu listy: auto-przewinięcie).
  await listbox.getByRole('option', { name: nameRe(gusName) }).click()
  await expect(chipLabel(dialog)).toHaveText(gusName)
  await expect(listbox).toBeHidden()

  // Ten sam warunek na wąskim ekranie (390×844).
  await page.setViewportSize(VIEWPORT_NARROW)
  await datasetsField(dialog).click()
  await expect(listbox).toBeVisible()
  await noOverlap('390')
  await shot(page, 's31-sc10-31baz-390-list-open')
  // Escape przy OTWARTEJ liście zamyka tylko listę (przy zamkniętej zamknąłby okno — U7).
  await page.keyboard.press('Escape')
  await expect(listbox).toBeHidden()
  await expect(dialog).toBeVisible()

  await dialog.getByRole('button', { name: 'Utwórz', exact: true }).click()
  await expect(page).toHaveURL(/\/chat\/[^/]+$/)
  chatIds.push(chatIdFromUrl(page))
  await expectNoLayoutDefects(page, 'SC-V13-10 31 baz: czat utworzony bez zamykania listy ręką')
})
