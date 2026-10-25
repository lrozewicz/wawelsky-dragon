// Scenariusz S6-12 (08 §7.8, §8.3; BRIEF E4-4b pkt 5, kontrakt WP E4-4b §„Zakres" p. 5; modal
// cytowania wg kontraktu WP E5-H3 §Decyzje UX #7): wyszukiwarka z listy — utworzenie (nazwa →
// `/search/:id`), ustawienia (baza z dokumentem, podsumowanie AI z modelem fake-llm, pytania
// pokrewne), zapytanie → podsumowanie z chipem cytowania otwierającym MODAL z pełnym fragmentem
// i trafieniami, chip pytania pokrewnego uruchamia nowe zapytanie, klik „Otwórz dokument” otwiera
// szufladę podglądu, zmiana nazwy utrwalona po F5, usunięcie z listy.
// Backend nie jest mockowany — te same trasy woła UI (wsiew przez API: `seedCorpus`, jak S6-05/S6-07).
// Krok chipa wraca na prawdziwy backend po rozszerzeniu fake-llm o pytania pokrewne (DEC-190,
// zastępuje obejście DEC-177, które poprzestawało na przechwyceniu żądania rekomendacji).
import type { APIRequestContext, Locator, Page } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { expectNoSeriousA11y } from './helpers/axe'
import { apiLogin, loginViaUi, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'
import { deleteAllSearches } from './helpers/searches'

const DATASET_NAME = 'E2E S6-12 baza'
const DOCUMENT_NAME = 'e2e-s12-smok.txt'
// Jeden akapit > 1000 znaków: chip cytowania pokazuje PEŁNĄ treść chunku (kontrakt WP E5-H3 #7),
// więc asercja na końcówkę fragmentu łapie przycięcie do 600 znaków z dawnego popovera.
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
/** Końcówka długiego fragmentu — widoczna tylko przy pełnej, nieprzyciętej treści (kontrakt #7). */
const LONG_TAIL = 'KONIEC-FRAGMENTU-SMOKA.'
const VIEWPORT_WIDE = { width: 1280, height: 800 }
const VIEWPORT_NARROW = { width: 390, height: 844 }

/**
 * Wymaga, by cały element mieścił się w viewporcie (kontrakt WP E5-H3 §Plan testów e2e):
 * `x/y ≥ 0` oraz `x+width/y+height ≤` wymiarów okna.
 */
async function expectInsideViewport(page: Page, locator: Locator, what: string): Promise<void> {
  const box = await locator.boundingBox()
  const viewport = page.viewportSize()
  expect(viewport, 'viewport').not.toBeNull()
  expect(box, `${what}: boundingBox`).not.toBeNull()
  expect(
    box!.x >= 0 &&
      box!.y >= 0 &&
      box!.x + box!.width <= viewport!.width &&
      box!.y + box!.height <= viewport!.height,
    `${what}: ${JSON.stringify(box)} w viewporcie ${viewport!.width}×${viewport!.height}`,
  ).toBe(true)
}
/** Pytanie zawiera słowa dokumentu — retrieval trafia w chunk, a fake-llm cytuje blok wiedzy. */
const QUESTION = 'Gdzie mieszkał smok wawelski i kto go pokonał?'
const SEARCH_NAME = 'E2E S6-12 wyszukiwarka'
const RENAMED_NAME = 'E2E S6-12 wyszukiwarka (po zmianie)'
/** Model podsumowania z rejestru fake-llm (K9 §3 p. 4) — `widoczna` nazwa opcji w formularzu. */
const SUMMARY_MODEL = 'fake-chat'
/** Podsumowanie ze strumienia i trafienia liczą się dłużej niż domyślne 5 s Playwrighta. */
const ANSWER_TIMEOUT_MS = 45_000
/** Pierwsze z pytań pokrewnych, które fake-llm zwraca na `Keywords:` (K10 §4, DEC-190). */
const RELATED_QUESTION = 'Pytanie pokrewne pierwsze'

type Shared = { token: string; corpus: SeededCorpus }

// Baza wiedzy z dokumentem jest wspólna dla całego pliku (parse to kilkanaście sekund), a reset
// K9 biegnie raz, przed całym biegiem — dlatego wsiewamy raz i trzymamy w module.
let shared: Promise<Shared> | undefined

function seeded(request: APIRequestContext): Promise<Shared> {
  shared ??= (async () => {
    const token = await apiLogin(request)
    const corpus = await seedCorpus(request, token, {
      datasetName: DATASET_NAME,
      documentName: DOCUMENT_NAME,
      documentBody: DOCUMENT_BODY,
    })
    return { token, corpus }
  })()
  return shared
}

// Scenariusz zostawia po sobie wyszukiwarki w bazie — sprzątamy je po biegu (kontrakt §7).
test.afterAll(async ({ request }) => {
  const current = shared === undefined ? undefined : await shared
  if (current !== undefined) await deleteAllSearches(request, current.token)
})

test('S6-12: wyszukiwarka z listy, podsumowanie z cytowaniem, trafienia i usunięcie', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  // Reset przed biegiem: lista wyszukiwarek ma startować pusta, a limiter logowania (10/min,
  // `auth_ratelimit.py`) liczy też próby UDANE — bez resetu S6-12, jako ostatni scenariusz
  // z logowaniem, dostawałby „Too many login attempts" (jak S6-05).
  await resetDb(request)
  await seeded(request)

  // 1. Logowanie kontem z seedu K9 (jak S6-01) i przejście na listę wyszukiwarek.
  await loginViaUi(page)
  const nav = page.getByRole('navigation')
  await nav.getByRole('link', { name: 'Wyszukiwanie' }).click()
  await expect(page).toHaveURL(/\/searches$/)
  const empty = page.getByTestId('empty-state')
  await expect(empty).toContainText('Nie masz jeszcze wyszukiwarek')

  // 2. Utworzenie z pustego stanu: sama nazwa → od razu `/search/:id`.
  await empty.getByRole('button', { name: 'Utwórz wyszukiwarkę' }).click()
  const createDialog = page.getByRole('dialog')
  await createDialog.getByLabel('Nazwa').fill(SEARCH_NAME)
  await createDialog.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page).toHaveURL(/\/search\/[^/]+$/)
  const searchId = new URL(page.url()).pathname.replace('/search/', '')

  // 3. Świeża wyszukiwarka nie ma baz wiedzy, więc szuflada ustawień otwiera się sama (kontrakt §4).
  await expect(page.getByRole('heading', { name: 'Ustawienia wyszukiwarki' })).toBeVisible()
  await page.getByRole('combobox', { name: 'Bazy wiedzy' }).click()
  await page.getByRole('option', { name: DATASET_NAME }).click()
  await page.getByLabel('Podsumowanie AI').check()
  await page.getByRole('combobox', { name: 'Model podsumowania' }).click()
  await page.getByRole('option', { name: SUMMARY_MODEL, exact: true }).click()
  await page.getByLabel('Pytania pokrewne').check()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('button', { name: 'Zapisz' })).toBeHidden()

  // 4. F5: ustawienia wracają z backendu (`PUT` zapisał pełny `search_config`).
  await page.reload()
  await expect(page.getByTestId('search-welcome')).toBeVisible()

  // 5. Pytanie: podsumowanie (strumień) i trafienia startują równolegle, a przy włączonych
  //    „Pytaniach pokrewnych" UI woła też rekomendację, z której renderują się chipy (DEC-190).
  await page.getByLabel('Pytanie').fill(QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()

  const summary = page.getByTestId('summary-card')
  await expect(summary).toContainText('Na podstawie źródeł', { timeout: ANSWER_TIMEOUT_MS })
  await expect(summary.getByRole('button', { name: 'Cytowanie 1' })).toBeVisible()

  // 6. Trafienia: nazwa dokumentu jest przyciskiem otwierającym szufladę podglądu.
  const hit = page.getByTestId('search-hit').first()
  await expect(hit).toBeVisible({ timeout: ANSWER_TIMEOUT_MS })
  expect(await page.getByTestId('search-hit').count(), 'liczba trafień').toBeGreaterThanOrEqual(1)
  await expect(hit).toContainText(DOCUMENT_NAME)

  // Jasny motyw, główny ekran scenariusza: wyszukiwarka z podsumowaniem i trafieniami
  // (przed otwarciem modalnego podglądu dokumentu).
  await expectNoSeriousA11y(page, 'S6-12 wyszukiwarka z podsumowaniem i trafieniami')

  // 7. Chip cytowania w podsumowaniu (ten sam `CitationChip` co w czacie): klik otwiera modal
  //    z pełnym fragmentem, Esc zamyka i oddaje fokus, Enter otwiera, a modal mieści się
  //    w viewportach 1280×800 i 390×844 (kontrakt WP E5-H3 §Decyzje UX #7).
  const chip = summary.getByRole('button', { name: 'Cytowanie 1' })
  await chip.hover()
  await expect(page.getByRole('dialog')).toBeHidden()

  await chip.click()
  // Modal cytowania rozpoznajemy po zawartości (`cite-content`): szuflada podglądu dokumentu też
  // ma `role="dialog"`, więc samo `getByRole('dialog')` jest niejednoznaczne po jej otwarciu.
  const citeDialog = page.getByRole('dialog').filter({ has: page.getByTestId('cite-content') })
  await expect(citeDialog).toBeVisible()
  await expect(citeDialog).toContainText(DOCUMENT_NAME)
  await expect(citeDialog).toContainText(LONG_TAIL)
  await expect(citeDialog).toContainText(/Podobieństwo: \d+%/)

  await page.setViewportSize(VIEWPORT_WIDE)
  await expectInsideViewport(page, citeDialog, 'modal cytowania (1280×800)')
  await expectInsideViewport(page, citeDialog.getByTestId('cite-content'), 'fragment (1280×800)')
  // MUI `Dialog` wjeżdża z animacją `Fade`: `.MuiDialog-container` animuje `opacity` 0→1
  // w 225 ms (patrz `Dialog`/`Fade` w @mui/material). Axe-core wlicza opacity przodka w kolor
  // pierwszego planu i tła, więc badanie w trakcie animacji daje PRZEJŚCIOWE naruszenie
  // `color-contrast` (zmierzone: 3,69:1 — #677082 na #dddee0 — zamiast docelowych 7,09:1 —
  // #47536B na #F5F6FA). Czekamy na koniec animacji, żeby axe oceniał kolory docelowe.
  await expect(page.locator('.MuiDialog-container')).toHaveCSS('opacity', '1')
  await expectNoSeriousA11y(page, 'S6-12 modal cytowania')

  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()
  await expect(chip).toBeFocused()

  await chip.press('Enter')
  await expect(citeDialog).toBeVisible()
  await citeDialog.getByRole('button', { name: 'Zamknij' }).click()
  await expect(citeDialog).toBeHidden()

  // 8. Trafienie: „Otwórz dokument” otwiera szufladę podglądu dokumentu (w szerokim viewporcie,
  //    przed przełączeniem układu poniżej progu `md`).
  await page.getByRole('button', { name: `Otwórz dokument ${DOCUMENT_NAME}` }).click()
  const preview = page.getByRole('dialog')
  await expect(preview).toContainText(DOCUMENT_NAME)
  await expect(preview).toContainText('Wawelski smok mieszkał w jamie pod Wawelem')
  await page.getByRole('button', { name: 'Zamknij podgląd' }).click()
  await expect(preview).toBeHidden()

  // 9. Poniżej progu `md` układ strony przełącza się i komponent montuje się od nowa (stan modala
  //    przepada), więc modal otwieramy PO zmianie viewportu i sprawdzamy to samo w 390×844.
  await page.setViewportSize(VIEWPORT_NARROW)
  await chip.click()
  await expect(citeDialog).toBeVisible()
  await expectInsideViewport(page, citeDialog, 'modal cytowania (390×844)')
  await expectInsideViewport(page, citeDialog.getByTestId('cite-content'), 'fragment (390×844)')
  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()
  await page.setViewportSize(VIEWPORT_WIDE)

  // 10. Pytania pokrewne (DEC-190): fake-llm zwraca trzy pytania, więc sekcja chipów się renderuje,
  //    a klik w chip uruchamia NOWE zapytanie — pole dostaje tekst chipa, leci nowe podsumowanie
  //    z tym pytaniem, a karta startuje od zera.
  await expect(page.getByText('Pytania pokrewne', { exact: true })).toBeVisible({
    timeout: ANSWER_TIMEOUT_MS,
  })
  const firstChip = page.getByRole('button', { name: RELATED_QUESTION })
  await expect(firstChip).toBeVisible()
  await expect(page.getByRole('button', { name: 'Pytanie pokrewne drugie' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Pytanie pokrewne trzecie' })).toBeVisible()

  const firstSummary = await summary.innerText()
  // Nasłuchy PRZED klikiem — żądanie startuje natychmiast po kliku.
  //
  // Obecność żądania bierzemy z `page.waitForRequest`, a jego ciało z trasy z `route.continue()`:
  // middleware klienta API klonuje `Request` (`request.clone()`, by powtórzyć żądanie po 401),
  // a ciało klona Chromium wysyła strumieniem — DevTools nie podaje wtedy `postData`, więc
  // `postDataJSON()` zwraca `null` (diagnoza t8-fix-s05, ten sam wzorzec co s05-retrieval).
  // Trasa tylko obserwuje i puszcza żądanie dalej — odpowiedź idzie z backendu, a podmiana
  // koperty (`route.fulfill`) jest w e2e zakazana (DEC-152 p. 1).
  const newCompletion = page.waitForRequest(
    (request) =>
      request.method() === 'POST' &&
      request.url().includes(`/api/v1/searches/${searchId}/completions`),
  )
  const completionResponse = page.waitForResponse(
    (answer) =>
      answer.request().method() === 'POST' &&
      answer.url().includes(`/api/v1/searches/${searchId}/completions`),
  )
  const postedBody = new Promise<{ question?: string } | null>((resolve) => {
    void page.route(`**/api/v1/searches/${searchId}/completions`, async (route) => {
      resolve(route.request().postDataJSON() as { question?: string } | null)
      await route.continue().catch(() => undefined)
    })
  })
  await firstChip.click()
  await expect(page.getByLabel('Pytanie')).toHaveValue(RELATED_QUESTION)
  await newCompletion
  expect((await postedBody)?.question, 'nowe zapytanie w ciele żądania').toBe(RELATED_QUESTION)
  // 200 domyka krok: bez niego odmowa API (np. 500) zostawiłaby kartę w stanie błędu, którego
  // sam `expect.poll` na różnicę tekstu nie odróżnia od poprawnego nowego podsumowania.
  const completionsAnswer = await completionResponse
  expect(
    completionsAnswer.status(),
    `POST /api/v1/searches/{id}/completions → HTTP ${completionsAnswer.status()}`,
  ).toBe(200)
  // Nowe zapytanie ma WŁASNE podsumowanie: karta startuje od zera, więc tekst różni się od
  // poprzedniej odpowiedzi. Pytanie pokrewne nie ma słów dokumentu (0 trafień), ale model jest
  // mimo to wołany (jak upstream `async_ask`, E4-H2 T1), więc nowe podsumowanie jest NIEPUSTE.
  await expect
    .poll(() => summary.innerText(), {
      timeout: ANSWER_TIMEOUT_MS,
      message: 'podsumowanie po kliku chipa różni się od poprzedniego',
    })
    .not.toBe(firstSummary)
  await expect(summary.getByTestId('summary-content')).not.toBeEmpty()
  // Trafienia liczą się dla nowego pytania — baza wiedzy nie ma jego słów, więc lista jest pusta.
  await expect(page.getByTestId('search-hit')).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS })

  // 11. Powrót na listę i zmiana nazwy z menu karty; F5 potwierdza utrwalenie na backendzie.
  //    Kopertę `PUT` sprawdzamy z komunikatem backendu — inaczej odmowa API kończyłaby się
  //    gołym brakiem nowej nazwy na karcie (wzór: `askQuestion` z S6-05).
  await nav.getByRole('link', { name: 'Wyszukiwanie' }).click()
  await expect(page.getByTestId('search-card')).toContainText(SEARCH_NAME)
  await page.getByRole('button', { name: 'Menu wyszukiwarki' }).click()
  await page.getByRole('menuitem', { name: 'Zmień nazwę' }).click()
  const renameDialog = page.getByRole('dialog')
  await renameDialog.getByLabel('Nazwa').fill(RENAMED_NAME)
  const answered = page.waitForResponse(
    (answer) => answer.request().method() === 'PUT' && answer.url().includes('/api/v1/searches/'),
  )
  await renameDialog.getByRole('button', { name: 'Zapisz' }).click()
  const renamed = await answered
  const renamedBody = (await renamed.json()) as { code: number; message: string }
  expect(renamed.status(), `PUT /api/v1/searches/{id} → HTTP ${renamed.status()}`).toBe(200)
  expect(
    renamedBody.code,
    `PUT /api/v1/searches/{id} → code ${renamedBody.code}: ${renamedBody.message}`,
  ).toBe(0)
  await expect(page.getByTestId('search-card')).toContainText(RENAMED_NAME)
  await page.reload()
  await expect(page.getByTestId('search-card')).toContainText(RENAMED_NAME)

  // 12. Usunięcie z menu karty z potwierdzeniem; lista wraca do pustego stanu.
  await page.getByRole('button', { name: 'Menu wyszukiwarki' }).click()
  await page.getByRole('menuitem', { name: 'Usuń' }).click()
  const deleteDialog = page.getByRole('dialog')
  await expect(deleteDialog).toContainText(`Czy usunąć wyszukiwarkę „${RENAMED_NAME}”?`)
  await deleteDialog.getByRole('button', { name: 'Usuń' }).click()
  await expect(page.getByTestId('empty-state')).toContainText('Nie masz jeszcze wyszukiwarek')
})
