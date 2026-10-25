// SC-V13-z-01 (R): klik w chip cytowania ZARAZ po końcu strumienia — podgląd fragmentu zostaje
// otwarty. Refetch sesji (`invalidateQueries(sessionKeys.all(chatId))` po `done` w
// `useChatStream`) zamienia parę „live” na parę z historii; gdy klucze wiadomości się zmieniają,
// `CitationChip` montuje się od nowa i świeżo otwarty modal znika (USTERKA — test czerwony przed
// poprawką). Wyścig odtwarzamy deterministycznie: odpowiedź GET sesji (lista i szczegół —
// regex, bo glob `sessions*` nie łapie `sessions/{id}`: `*` w Playwrighcie nie przecina `/`)
// czeka w handlerze trasy, aż test kliknie chip w chwili zdarzenia końca strumienia, i dopiero
// wtedy ją puszczamy — zamiana przy otwartym modalu jest gwarantowana.
// Backend nie jest mockowany — spowalniamy wyłącznie przekazanie żądania do prawdziwego API.
import type { APIRequestContext, Page } from '@playwright/test'

import { ADMIN_EMAIL, ADMIN_PASSWORD, expect, test } from './fixtures'
import { apiLogin, createChat, deleteAllChats, seedCorpus } from './helpers'
import { expectNoLayoutDefects } from './helpers/layout'
import type { SeededCorpus } from './helpers'

const DATASET_NAME = 'E2E S32 baza'
// Długa nazwa bez spacji (QA-UI V13-z-2, MAJOR wizualny): na 390 px nie mieści się w tytule
// modalu cytowania, gdy ten nie zawija (`overflow-wrap: anywhere`) — jak
// „gus_rocznik_statystyczny_rp_2024.pdf” ze zgłoszenia QA.
const DOCUMENT_NAME = 'gus_rocznik_statystyczny_rp_2024_dane_miesieczne_opracowanie.txt'
// Jeden akapit > 1000 znaków (wzór S6-07): końcówka fragmentu odróżnia modal od przyciętego tekstu.
const DOCUMENT_BODY = [
  'Bazyliszek zamieszkiwał podziemia krakowskiej katedry, a jego spojrzenie zabijało każdego,',
  'kto odważył się zejść do krypt. Mieszkańcy Miasteczka bali się bazyliszka podziemnego, który',
  'porywał gołębie i króliki z kurników na Wzgórzu, więc rada miasta obiecała skarb temu, kto',
  'uwolni katedrę od potwora. Wielu śmiałków schodziło do podziemi, ale żaden nie wrócił z',
  'mroku pod fundamentami. Dopiero krawiec Bernard wpadł na pomysł, by zszedł do krypt z',
  'lusterkiem przed sobą, bo spojrzenie bazyliszka odbite wracało do nadawcy. Bazyliszek',
  'podziemny spojrzał we własne oko, skamieniał na miejscu i od tej pory stoi w kącie krypty',
  'jako posąg. Od tego czasu Miasteczko żyło w spokoju, a na pamiątkę zwycięstwa nad potworem',
  'postawiono przy katedrze rzeźbę krawca, która do dziś wskazuje lusterkiem ku uciesze',
  'turystów i mieszkańców. Przewodnicy po podziemiach pokazują kryptę bazyliszka i opowiadają,',
  'jak dzielny krawiec Bernard pokonał potwora podstępem, a nie siłą. Koniec opowieści',
  'o bazyliszku należy do najmłodszych podań o Miasteczku i do dziś opowiada się ją dzieciom',
  'w przedszkolach i szkołach podczas lekcji lokalnej historii. KONIEC-FRAGMENTU-BAZYLISZKA.',
].join(' ')
/** Końcówka długiego fragmentu — widoczna tylko przy pełnej, nieprzyciętej treści. */
const FRAGMENT_TAIL = 'KONIEC-FRAGMENTU-BAZYLISZKA.'
const VIEWPORT_NARROW = { width: 390, height: 844 }
// Pytanie zawiera słowa dokumentu — retrieval (prog 0.1, waga wektorowa 0.3) trafia w chunk.
const QUESTION = 'Gdzie zamieszkiwał bazyliszek i kto go pokonał?'
const CHAT_NAME = 'E2E S32 wyścig cytowania'

const SESSIONS = /\/api\/v1\/chats\/[^/]+\/sessions/
/** Bezpiecznik: wstrzymany refetch nie może wisieć wiecznie, gdy coś pójdzie nie tak. */
const HOLD_GUARD_MS = 30_000

type Shared = { token: string; corpus: SeededCorpus }

// Korpus jest wspólny dla obu testów w pliku (parse to kilkanaście sekund); reset bazy K9 biegnie
// raz w `global-setup.ts`, więc dane drugiego testu są nietknięte.
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

// Scenariusz zostawia po sobie czaty w bazie — sprzątamy jak S6-07.
test.afterAll(async ({ request }) => {
  const current = shared === undefined ? undefined : await shared
  if (current !== undefined) await deleteAllChats(request, current.token)
})

/**
 * Wstrzymuje odpowiedzi GET sesji do wywołania zwróconej funkcji („puść refetch”).
 * Żądania nie giną — po zwolnieniu lecą do prawdziwego backendu (`continue`).
 */
function holdSessionFetch(page: Page): () => void {
  let release!: () => void
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  void page.route(SESSIONS, async (route) => {
    await Promise.race([released, new Promise((resolve) => setTimeout(resolve, HOLD_GUARD_MS))])
    await route.continue().catch(() => undefined)
  })
  return release
}

/** Logowanie kontem z seedu K9 przez UI (jak S6-07). */
async function loginViaUi(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByTestId('login-email').fill(ADMIN_EMAIL)
  await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('home-banner')).toBeVisible()
}

/**
 * Scenariusz SC-V13-z-01, kroki 1–3: pytanie → klik w chip w chwili końca strumienia (przy
 * wstrzymanym refetchu sesji) → puszczenie refetchu → podgląd nadal otwarty po 3 s, ta sama
 * treść, bez zmiany pozycji dialogu. Wspólny trzon testów 1280 px i 390 px.
 */
async function citationSurvivesSessionRefetch(page: Page, corpus: SeededCorpus): Promise<void> {
  // Wyścig: refetch sesji czeka, aż test kliknie chip i jawnie go puści (krok 2).
  const releaseSessions = holdSessionFetch(page)

  await page.getByPlaceholder('Wpisz pytanie…').fill(QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()

  // Krok 1: odpowiedź strumieniowa z chipami cytowań.
  const answer = page.getByTestId('message-assistant').last()
  await expect(answer).toContainText('Na podstawie źródeł', { timeout: 30_000 })
  const chip = answer.getByRole('button', { name: 'Cytowanie 1' })
  await expect(chip).toBeVisible()
  // Zdarzenie końca strumienia: faza `done` wraca polem pytania do „Wyślij” — refetch już wisi
  // w handlerze trasy, więc między tym momentem a zwolnieniem nic nie zamieni pary live.
  await expect(page.getByRole('button', { name: 'Wyślij' })).toBeVisible()

  // Krok 2: klik natychmiast po ostatnim tokenie — modal otwarty z pełnym fragmentem.
  await chip.click()
  const citeDialog = page.getByRole('dialog').filter({ has: page.getByTestId('cite-content') })
  await expect(citeDialog).toBeVisible()
  await expect(citeDialog).toContainText(corpus.documentName)
  await expect(citeDialog).toContainText(FRAGMENT_TAIL)
  const boxBefore = await citeDialog.boundingBox()
  expect(boxBefore, 'boundingBox otwartego modala').not.toBeNull()

  // „Puść” wstrzymany refetch — para live zostaje zamieniona na parę z historii.
  releaseSessions()

  // Tu (przed poprawką) modal umiera: remont `CitationChip` zamyka świeżo otwarty podgląd.
  await expect(citeDialog, 'modal po zamianie live → historia').toBeVisible()

  // Krok 3: 3 s bez interakcji — podgląd nadal otwarty, ta sama treść, bez zmiany pozycji.
  await page.waitForTimeout(3_000)
  await expect(citeDialog).toBeVisible()
  await expect(citeDialog).toContainText(corpus.documentName)
  await expect(citeDialog).toContainText(FRAGMENT_TAIL)
  expect(await citeDialog.boundingBox(), 'pozycja modala po 3 s').toEqual(boxBefore)
}

test('SC-V13-z-01: modal cytowania zostaje otwarty po refetchu sesji (1280×800)', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000)
  const { token, corpus } = await seeded(request)
  const chatId = await createChat(request, token, {
    name: CHAT_NAME,
    datasetIds: [corpus.datasetId],
  })

  await loginViaUi(page)
  await page.goto(`/chat/${chatId}`)

  await citationSurvivesSessionRefetch(page, corpus)

  const citeDialog = page.getByRole('dialog').filter({ has: page.getByTestId('cite-content') })
  const chip = page
    .getByTestId('message-assistant')
    .last()
    .getByRole('button', { name: 'Cytowanie 1' })
  await expectNoLayoutDefects(page, 'modal cytowania po refetchu (SC-V13-z-01)')

  // Krok 4: Esc zamyka i ponowne kliknięcie otwiera; „Zamknij” też zamyka.
  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()
  await expect(chip).toBeFocused()
  await chip.click()
  await expect(citeDialog).toBeVisible()
  await citeDialog.getByRole('button', { name: 'Zamknij' }).click()
  await expect(citeDialog).toBeHidden()

  // Odświeżenie strony: historia zawiera tę samą odpowiedź z działającymi chipami.
  await page.reload()
  const historyChip = page
    .getByTestId('message-assistant')
    .last()
    .getByRole('button', { name: 'Cytowanie 1' })
  await expect(historyChip).toBeVisible()
  await historyChip.click()
  await expect(citeDialog).toBeVisible()
  await expect(citeDialog).toContainText(FRAGMENT_TAIL)
  await expectNoLayoutDefects(page, 'modal cytowania po odświeżeniu (SC-V13-z-01)')
  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()
})

test('SC-V13-z-01: to samo na 390 px — podgląd zostaje otwarty po refetchu', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000)
  const { token, corpus } = await seeded(request)
  const chatId = await createChat(request, token, {
    name: `${CHAT_NAME} mobile`,
    datasetIds: [corpus.datasetId],
  })

  await page.setViewportSize(VIEWPORT_NARROW)
  await loginViaUi(page)
  await page.goto(`/chat/${chatId}`)

  await citationSurvivesSessionRefetch(page, corpus)

  // Krok 5 (390 px): dialog mieści się w viewporcie (U12), Esc zamyka, chip działa dalej.
  const citeDialog = page.getByRole('dialog').filter({ has: page.getByTestId('cite-content') })
  await expectNoLayoutDefects(page, 'modal cytowania 390 px po refetchu (SC-V13-z-01)')
  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()

  const chip = page
    .getByTestId('message-assistant')
    .last()
    .getByRole('button', { name: 'Cytowanie 1' })
  await chip.click()
  await expect(citeDialog).toBeVisible()
  // QA-UI V13-z-2: pełna nazwa dokumentu czytelna na 390 px — tytuł zawija, nic nie jest ucięte.
  // Przed poprawką (`overflow-wrap: anywhere` na DialogTitle) długa nazwa przelewała się:
  // scrollWidth ~750 > clientWidth 356 przy `text-overflow: clip`, bez dymku.
  const titleMetrics = await citeDialog
    .locator('.MuiDialogTitle-root')
    .evaluate((el) => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }))
  expect(
    titleMetrics.scrollWidth,
    `tytuł mieści się w 390 px bez ucięcia: ${JSON.stringify(titleMetrics)}`,
  ).toBeLessThanOrEqual(titleMetrics.clientWidth)
  const viewport = page.viewportSize()
  expect(viewport, 'viewport 390×844').not.toBeNull()
  const box = await citeDialog.boundingBox()
  expect(box, 'boundingBox modala 390 px').not.toBeNull()
  expect(
    box!.x >= 0 &&
      box!.y >= 0 &&
      box!.x + box!.width <= viewport!.width &&
      box!.y + box!.height <= viewport!.height,
    `modal 390 px: ${JSON.stringify(box)} w viewporcie ${viewport!.width}×${viewport!.height}`,
  ).toBe(true)
  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()
})
