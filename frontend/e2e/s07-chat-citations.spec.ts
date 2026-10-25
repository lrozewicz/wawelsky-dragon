// Scenariusz S6-07 (08 §11.2; kontrakt WP E3-5b §„e2e (T7)", kontrakt WP E5-H3 §Decyzje UX #7):
// czat z bazą wiedzy i modelem z myśleniem (fake-chat-think) odpowiada na pytanie streamem —
// widać sekcję „Myślenie…", treść odpowiedzi, chip cytowania otwierający MODAL z pełnym
// fragmentem źródła (nazwa dokumentu, pełna treść, podobieństwo) i szufladę podglądu dokumentu
// po kliknięciu „Otwórz dokument". Drugi test: Stop przerywa trwający stream.
// Backend nie jest mockowany — spowalniamy wyłącznie przekazanie żądania do prawdziwego API.
import type { APIRequestContext, Locator, Page } from '@playwright/test'

import { ADMIN_EMAIL, ADMIN_PASSWORD, expect, test } from './fixtures'
import { apiLogin, createChat, deleteAllChats, seedCorpus } from './helpers'
import { expectNoSeriousA11y } from './helpers/axe'
import type { SeededCorpus } from './helpers'

const DATASET_NAME = 'E2E S6-07 baza'
const DOCUMENT_NAME = 'e2e-s07-smok.txt'
// Jeden akapit > 1000 znaków: chip cytowania pokazuje PEŁNĄ treść chunku, więc asercja na końcówkę
// fragmentu odróżnia modal od dawnego popovera przycinającego treść do 600 znaków (kontrakt #7).
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
// Pytanie zawiera słowa dokumentu — retrieval (prog 0.1, waga wektorowa 0.3) trafia w chunk.
const QUESTION = 'Gdzie mieszkał smok wawelski i kto go pokonał?'
const CHAT_NAME = 'E2E S6-07 czat'
const THINK_MODEL = 'fake-chat-think'
/** Prompt systemowy z placeholderem `{knowledge}` — bez niego formularz nie zapisze bazy. */
const SYSTEM_PROMPT = 'Odpowiadaj na podstawie przekazanej wiedzy.\n\n{knowledge}'

const COMPLETIONS = '**/api/v1/chats/*/completions'
/** Opóźnienie przekazania żądania `completions` do backendu (test Stop). */
const SLOW_REQUEST_MS = 4_000

type Shared = { token: string; corpus: SeededCorpus }

// Baza wiedzy z dokumentem jest wspólna dla obu testów w pliku (parse to kilkanaście sekund);
// reset bazy K9 biegnie raz, w `global-setup.ts`, więc dane drugiego testu są nietknięte.
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

// Scenariusz zostawia po sobie czaty w bazie — `s07a-chats-list.spec.ts` startuje od pustej listy.
test.afterAll(async ({ request }) => {
  const current = shared === undefined ? undefined : await shared
  if (current !== undefined) await deleteAllChats(request, current.token)
})

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

/** Logowanie kontem z seedu K9 przez UI (jak S6-01 i S7a). */
async function loginViaUi(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByTestId('login-email').fill(ADMIN_EMAIL)
  await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('home-banner')).toBeVisible()
}

test('S6-07: czat z bazą wiedzy, cytowaniem i podglądem dokumentu', async ({ page, request }) => {
  test.setTimeout(180_000)
  await seeded(request)

  // 1. Czat tworzymy z UI (pusty stan listy „Utwórz czat” albo przycisk w nagłówku strony).
  await loginViaUi(page)
  await page.getByRole('navigation').getByRole('link', { name: 'Czat' }).click()
  await expect(page).toHaveURL(/\/chats$/)
  await page.getByRole('button', { name: 'Utwórz czat' }).first().click()
  const createDialog = page.getByRole('dialog')
  await createDialog.getByLabel('Nazwa').fill(CHAT_NAME)
  await createDialog.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page).toHaveURL(/\/chat\/[^/]+$/)

  // 2. Szuflada ustawień: baza wiedzy w zakładce „Asystent", model z myśleniem w „Model".
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  await page.getByRole('combobox', { name: 'Bazy wiedzy' }).click()
  await page.getByRole('option', { name: DATASET_NAME }).click()
  // Czat bez bazy startuje z pustym promptem systemowym, a wybór bazy sam wypełnia pole
  // szablonem z `{knowledge}` (C2 WP E5-H6e), więc ostrzeżenie walidacji się nie pojawia —
  // w zakładce „Silnik promptu" sprawdzamy wartość pola, nie komunikat.
  await page.getByRole('tab', { name: 'Silnik promptu' }).click()
  await expect(page.getByLabel('Prompt systemowy')).toHaveValue(/\{knowledge\}/)
  await expect(
    page.getByText('Prompt systemowy musi zawierać {knowledge}, gdy wybrano bazy wiedzy.'),
  ).toHaveCount(0)
  await page.getByLabel('Prompt systemowy').fill(SYSTEM_PROMPT)
  await page.getByRole('tab', { name: 'Model' }).click()
  await page.getByRole('combobox', { name: 'Model' }).click()
  await page.getByRole('option', { name: THINK_MODEL }).click()
  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()

  // 3. Pytanie i odpowiedź streamowana.
  await page.getByPlaceholder('Wpisz pytanie…').fill(QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()

  const answer = page.getByTestId('message-assistant').last()
  await expect(answer).toContainText('Na podstawie źródeł', { timeout: 30_000 })

  // 4. Sekcja „Myślenie…" została zwinięta po zakończeniu streamu — otwieramy ją ręcznie.
  const thinking = page.getByRole('button', { name: 'Myślenie…' })
  await expect(thinking).toBeVisible()
  if ((await thinking.getAttribute('aria-expanded')) === 'false') await thinking.click()
  await expect(page.getByText('Rozważam pytanie.')).toBeVisible()

  // Główny ekran scenariusza: czat z odpowiedzią i cytowaniem (jasny motyw).
  await expectNoSeriousA11y(page, 'S6-07 czat')

  // 5. Chip cytowania: hover nic nie otwiera, klik otwiera modal z PEŁNYM fragmentem źródła.
  const chip = page.getByRole('button', { name: 'Cytowanie 1' })
  await expect(chip).toBeVisible()
  await chip.hover()
  await expect(page.getByRole('dialog')).toBeHidden()

  await chip.click()
  // Modal cytowania rozpoznajemy po zawartości (`cite-content`): szuflada podglądu dokumentu też
  // ma `role="dialog"`, więc samo `getByRole('dialog')` jest niejednoznaczne po jej otwarciu.
  const citeDialog = page.getByRole('dialog').filter({ has: page.getByTestId('cite-content') })
  await expect(citeDialog).toBeVisible()
  // Nazwa dokumentu jest nagłówkiem (etykieta dialogu), treść bez przycięcia do 600 znaków.
  await expect(citeDialog).toContainText(DOCUMENT_NAME)
  await expect(citeDialog).toContainText(LONG_TAIL)
  await expect(citeDialog).toContainText(/Podobieństwo: \d+%/)

  // 6. Cały dialog i przewijany fragment mieszczą się w viewporcie 1280×800; modal jest dostępny.
  await page.setViewportSize(VIEWPORT_WIDE)
  await expectInsideViewport(page, citeDialog, 'modal cytowania (1280×800)')
  await expectInsideViewport(page, citeDialog.getByTestId('cite-content'), 'fragment (1280×800)')
  // MUI `Dialog` wjeżdża z animacją `Fade`: `.MuiDialog-container` animuje `opacity` 0→1
  // w 225 ms (patrz `Dialog`/`Fade` w @mui/material). Axe-core wlicza opacity przodka w kolor
  // pierwszego planu i tła, więc badanie w trakcie animacji daje PRZEJŚCIOWE naruszenie
  // `color-contrast` (zmierzone: 3,69:1 — #677082 na #dddee0 — zamiast docelowych 7,09:1 —
  // #47536B na #F5F6FA). Czekamy na koniec animacji, żeby axe oceniał kolory docelowe.
  await expect(page.locator('.MuiDialog-container')).toHaveCSS('opacity', '1')
  await expectNoSeriousA11y(page, 'S6-07 modal cytowania')

  // 7. Esc zamyka i oddaje fokus chipowi; Enter otwiera ponownie.
  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()
  await expect(chip).toBeFocused()

  await chip.press('Enter')
  await expect(citeDialog).toBeVisible()

  // 8. „Otwórz dokument” zamyka modal i otwiera szufladę podglądu z treścią dokumentu.
  await citeDialog.getByRole('button', { name: 'Otwórz dokument' }).click()
  // Czekamy na domknięcie modala (animacja MUI), zanim wskażemy szufladę podglądu — inaczej
  // `getByRole('dialog')` trafia na dwa dialogi naraz (strict mode).
  await expect(citeDialog).toBeHidden()
  const preview = page.getByRole('dialog')
  await expect(preview).toContainText(DOCUMENT_NAME)
  await expect(preview).toContainText('Wawelski smok mieszkał w jamie pod Wawelem')
  // Esc zamyka podgląd i oddaje fokus wyzwalaczowi — chipowi cytowania (MINOR QA E5-H3 #7).
  await page.keyboard.press('Escape')
  await expect(preview).toBeHidden()
  await expect(chip).toBeFocused()

  // 9. Poniżej progu `md` strona czatu przełącza układ i chip montuje się od nowa (stan modala
  //    przepada), więc modal otwieramy PO zmianie viewportu i sprawdzamy to samo w 390×844.
  await page.setViewportSize(VIEWPORT_NARROW)
  await chip.click()
  await expect(citeDialog).toBeVisible()
  await expect(citeDialog).toContainText(LONG_TAIL)
  await expectInsideViewport(page, citeDialog, 'modal cytowania (390×844)')
  await expectInsideViewport(page, citeDialog.getByTestId('cite-content'), 'fragment (390×844)')
  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()
  await page.setViewportSize(VIEWPORT_WIDE)
})

test('S6-07: Stop przerywa stream', async ({ page, request }) => {
  test.setTimeout(120_000)
  const { token, corpus } = await seeded(request)
  const chatId = await createChat(request, token, {
    name: 'E2E S6-07 stop',
    datasetIds: [corpus.datasetId],
  })

  // Spowolnienie WYŁĄCZNIE przekazania żądania do prawdziwego backendu (odpowiedź nie jest
  // mockowana) — bez tego fake-llm kończy stream zanim zdążymy kliknąć Stop.
  await page.route(COMPLETIONS, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, SLOW_REQUEST_MS))
    // Stop przerywa żądanie po stronie przeglądarki, więc `continue()` może już nie mieć czego
    // przekazać — to oczekiwany skutek anulowania, nie błąd scenariusza.
    await route.continue().catch(() => undefined)
  })

  await loginViaUi(page)
  await page.goto(`/chat/${chatId}`)
  await page.getByPlaceholder('Wpisz pytanie…').fill(QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()

  await page.getByRole('button', { name: 'Zatrzymaj' }).click()

  // Anulowana wiadomość dostaje status `aborted` — chip „Przerwano", bez treści odpowiedzi.
  await expect(page.getByText('Przerwano')).toBeVisible()
  await expect(page.getByTestId('message-assistant').last()).not.toContainText(
    'Na podstawie źródeł',
  )
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})
