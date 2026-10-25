// SC-V12-05 (work/wp/V12/SCENARIOS.md): domyślne teksty czatu — powitanie i „odpowiedź przy
// braku wyników" — w języku interfejsu przy tworzeniu czatu (K20 §5 p. 3; DEC-358). Testy pisane
// PRZED poprawką: dziś UI wysyła tylko `prologue`, więc `empty_response` nowego czatu zostaje
// z domyślnym (angielskim) tekstem serwera — test a pada z tej przyczyny, c (czat sprzed v1.2
// przez API bez `prompt_config`) i d (UI EN) są próbami kontrolnymi: c nie może ulec migracji,
// a d jest zielony i przed, i po poprawce (teksty EN = teksty serwera). Wzorce:
// s16c-chat-empty-response.spec.ts (próg podobieństwa przez API, treść niezwiązana z pytaniem),
// s28-v12-discard.spec.ts (uiSession, setProfileLanguage, zrzuty jasny/ciemny).
import type { APIRequestContext, APIResponse, Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const SHOTS = process.env.WD_SHOTS_DIR ?? ''

// Domyślne teksty serwera (backend/app/domain/chat/config.py) i klucze i18n (locales/*/chat.json).
const EN_PROLOGUE = "Hi! I'm your assistant. What can I do for you?"
const EN_EMPTY = 'Sorry! No relevant content was found in the knowledge base!'
const PL_PROLOGUE = 'Cześć! Jestem Twoim asystentem. W czym mogę pomóc?'
const PL_EMPTY = 'Nie znaleziono pasujących treści w bazie wiedzy.'

const DATASET_NAME = 'E2E V12-05 baza bez trafien'
const DOCUMENT_NAME = 'e2e-v12-05-prognoza.txt'
/** Treść niezwiązana z pytaniem — retrieval nie ma czego trafić (wzór: s16c). */
const DOCUMENT_BODY =
  'Prognoza pogody na najbliższy tydzień przewiduje opady deszczu i silny wiatr w całym kraju. ' +
  'Meteorolodzy ostrzegają przed burzami i zalecają pozostanie w domach.'
const QUESTION = 'Ile waży dorodny arbuz z ogrodu babci?'

type Envelope<T> = { code: number; message: string; data: T }

async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

const session = uiSession('s28-v12-chat-texts')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(240_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

let corpus: SeededCorpus
let token = ''
let legacyChatId = '' // c: API bez `prompt_config` — jak tworzyło dziś UI sprzed v1.2.
/** Czaty do sprzątania po biegu (dokowują je kolejne testy — także przy biegach pojedynczych). */
const chatIds: string[] = []
test.beforeAll(async ({ request }) => {
  token = await apiLogin(request)
  corpus = await seedCorpus(request, token, {
    datasetName: DATASET_NAME,
    documentName: DOCUMENT_NAME,
    documentBody: DOCUMENT_BODY,
  })
  legacyChatId = await createChat(request, token, { name: `E2E V12-05 legacy ${Date.now()}` })
  chatIds.push(legacyChatId)
})
test.afterAll(async ({ request }) => {
  if (chatIds.length > 0) {
    await request.delete(`${API_URL}/api/v1/chats`, {
      headers: { authorization: `Bearer ${token}` },
      data: { ids: chatIds },
    })
  }
  await deleteDataset(request, token, corpus.datasetId)
  await setProfileLanguage(request, token, 'pl')
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Koniec animacji wejścia szuflady przed pomiarem/zrzutem (wzór: s28-v12-discard). */
async function drawerSettled(page: Page, drawer: Locator): Promise<void> {
  const viewportWidth = page.viewportSize()?.width ?? 0
  await expect
    .poll(async () => {
      const box = await drawer.boundingBox()
      return box === null ? Number.POSITIVE_INFINITY : box.x + box.width
    })
    .toBeLessThanOrEqual(viewportWidth)
}

/** Koniec animacji WYJŚCIA szuflady — strażnik układu mierzy ekran już po teście (wzór: s28). */
async function drawerGone(drawer: Locator): Promise<void> {
  await expect.poll(async () => await drawer.count()).toBe(0)
}

/** Etykiety UI zależne od języka interfejsu (PL/EN równolegle). */
const LANG = {
  pl: {
    create: 'Utwórz czat',
    createSubmit: 'Utwórz',
    name: 'Nazwa',
    settingsButton: 'Ustawienia czatu',
    drawerTitle: 'Ustawienia czatu',
    assistantTab: 'Asystent',
    prologueLabel: 'Powitanie',
    emptyResponseLabel: 'Odpowiedź przy braku wyników',
    save: 'Zapisz',
    saved: 'Zapisano ustawienia czatu.',
    questionPlaceholder: 'Wpisz pytanie…',
    send: 'Wyślij',
  },
  en: {
    create: 'Create chat',
    createSubmit: 'Create',
    name: 'Name',
    settingsButton: 'Chat settings',
    drawerTitle: 'Chat settings',
    assistantTab: 'Assistant',
    prologueLabel: 'Greeting',
    emptyResponseLabel: 'Response when nothing is found',
    save: 'Save',
    saved: 'Chat settings saved.',
    questionPlaceholder: 'Type your question…',
    send: 'Send',
  },
} as const
type Lang = keyof typeof LANG

/**
 * Tworzy czat przyciskiem „Utwórz czat” w prawdziwym UI (Czaty → dialog nazwy → „Utwórz”) i
 * zwraca jego id z adresu `/chat/:id`, na który UI przechodzi automatycznie po utworzeniu.
 */
async function createChatViaUi(page: Page, lang: Lang, name: string): Promise<string> {
  const labels = LANG[lang]
  await page.goto('/chats')
  await page.getByRole('button', { name: labels.create }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel(labels.name).fill(name)
  await dialog.getByRole('button', { name: labels.createSubmit }).click()
  await page.waitForURL(/\/chat\//)
  const id = /\/chat\/([^/?]+)/.exec(page.url())?.[1]
  expect(id, 'adres po utworzeniu czatu zawiera id').toBeDefined()
  return id as string
}

/**
 * Dołącza bazę z niezwiązaną treścią i podnosi próg podobieństwa do 0.9 (0 trafień, jak s16c).
 * PATCH scala `prompt_config` (`services/chats.py`: `{**current, **patch}`), więc teksty
 * ustawione przy tworzeniu zostają — zmieniamy wyłącznie `refine_multiturn`.
 */
async function attachBaseWithNoHits(request: APIRequestContext, chatId: string): Promise<void> {
  await ok<unknown>(
    request.patch(`${API_URL}/api/v1/chats/${chatId}`, {
      headers: { authorization: `Bearer ${token}` },
      data: {
        dataset_ids: [corpus.datasetId],
        similarity_threshold: 0.9,
        prompt_config: { refine_multiturn: false },
      },
    }),
    'PATCH /api/v1/chats/{id}',
  )
}

/** Wpisuje pytanie w polu rozmowy i wysyła je przyciskiem (etykiety wg języka UI). */
async function ask(page: Page, lang: Lang, question: string): Promise<void> {
  const labels = LANG[lang]
  await page.getByPlaceholder(labels.questionPlaceholder).fill(question)
  await page.getByRole('button', { name: labels.send }).click()
}

/**
 * Otwiera szufladę ustawień czatu na zakładce „Asystent”; zwraca lokator szuflady
 * (po treści nagłówka — paper nie ma `aria-label`, wzór: s28-v12-discard).
 */
async function openAssistantTab(page: Page, lang: Lang): Promise<Locator> {
  const labels = LANG[lang]
  await page.getByRole('button', { name: labels.settingsButton }).click()
  const drawer = page.locator('.MuiDrawer-paper').filter({ hasText: labels.drawerTitle })
  await expect(drawer).toBeVisible()
  await page.getByRole('tab', { name: labels.assistantTab }).click()
  return drawer
}

test('SC-V12-05 a: nowy czat z UI PL — powitanie po polsku, pytanie spoza bazy → polska odpowiedź', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const plChatId = await createChatViaUi(page, 'pl', `E2E V12-05 czat PL ${Date.now()}`)
  chatIds.push(plChatId)
  await attachBaseWithNoHits(request, plChatId)

  await ask(page, 'pl', QUESTION)
  // Odpowiedź przy braku trafień — w języku UI, nie domyślny tekst serwera.
  const answer = page.getByTestId('message-assistant').last()
  await expect(answer).toContainText(PL_EMPTY, { timeout: 30_000 })
  await expect(answer).not.toContainText(EN_EMPTY)

  // Powitanie (prologue) trafia do historii sesji jako pierwszy dymek asystenta.
  await expect(page.getByTestId('message-assistant').first()).toContainText(PL_PROLOGUE, {
    timeout: 30_000,
  })
})

test('SC-V12-05 b: ustawienia czatu PL — polskie wartości pól, edycja przetrwa F5', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  chatIds.push(await createChatViaUi(page, 'pl', `E2E V12-05 ustawienia ${Date.now()}`))

  const drawer = await openAssistantTab(page, 'pl')
  const prologue = drawer.getByLabel(LANG.pl.prologueLabel)
  const emptyResponse = drawer.getByLabel(LANG.pl.emptyResponseLabel)
  await expect(prologue).toHaveValue(PL_PROLOGUE)
  await expect(emptyResponse).toHaveValue(PL_EMPTY)

  // Edytowalność: wpisany tekst przetrwa zapis i odświeżenie strony.
  await prologue.fill('Cześć! (e2e)')
  await emptyResponse.fill('Brak trafień (e2e)')
  await page.getByRole('button', { name: LANG.pl.save }).click()
  await expect(page.getByText(LANG.pl.saved)).toBeVisible()
  await drawerGone(drawer)

  await page.reload()
  await openAssistantTab(page, 'pl')
  await expect(prologue).toHaveValue('Cześć! (e2e)')
  await expect(emptyResponse).toHaveValue('Brak trafień (e2e)')

  // Koniec animacji wyjścia szuflady — strażnik układu mierzy ekran po teście.
  await page.keyboard.press('Escape')
  await drawerGone(drawer)
})

test('SC-V12-05 c: czat sprzed v1.2 (API bez prompt_config) — teksty angielskie bez migracji', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/chat/${legacyChatId}`)

  const drawer = await openAssistantTab(page, 'pl')
  await expect(drawer.getByLabel(LANG.pl.prologueLabel)).toHaveValue(EN_PROLOGUE)
  await expect(drawer.getByLabel(LANG.pl.emptyResponseLabel)).toHaveValue(EN_EMPTY)

  await page.keyboard.press('Escape')
  await drawerGone(drawer)
})

test('SC-V12-05 d: nowy czat z UI EN — teksty angielskie (kontrola)', async ({ page, request }) => {
  await setProfileLanguage(request, token, 'en')
  try {
    await page.setViewportSize({ width: 1280, height: 800 })
    const enChatId = await createChatViaUi(page, 'en', `E2E V12-05 chat EN ${Date.now()}`)
    chatIds.push(enChatId)
    await attachBaseWithNoHits(request, enChatId)

    await ask(page, 'en', QUESTION)
    const answer = page.getByTestId('message-assistant').last()
    await expect(answer).toContainText(EN_EMPTY, { timeout: 30_000 })

    await expect(page.getByTestId('message-assistant').first()).toContainText(EN_PROLOGUE, {
      timeout: 30_000,
    })
  } finally {
    await setProfileLanguage(request, token, 'pl')
  }
})

test('SC-V12-05 e: zrzuty ustawień czatu 1280/390, jasny i ciemny', async ({ page }) => {
  // Własny czat (test ma być odpalalny pojedynczo `-g`): teksty domyślne z UI PL, bez bazy —
  // szuflada tylko do oglądu, zapisu nie ma.
  const shotsChatId = await createChatViaUi(page, 'pl', `E2E V12-05 zrzuty ${Date.now()}`)
  chatIds.push(shotsChatId)
  for (const [name, width, height, dark] of [
    ['1280-jasny', 1280, 800, false],
    ['1280-ciemny', 1280, 800, true],
    ['390-jasny', 390, 844, false],
    ['390-ciemny', 390, 844, true],
  ] as const) {
    await page.emulateMedia({ colorScheme: dark ? 'dark' : 'light' })
    await page.setViewportSize({ width, height })
    await page.goto(`/chat/${shotsChatId}`)
    const drawer = await openAssistantTab(page, 'pl')
    await expect(drawer.getByLabel(LANG.pl.prologueLabel)).toBeVisible()
    await drawerSettled(page, drawer)
    await page.waitForTimeout(100)
    await shot(page, `sc-v12-05-settings-${name}`)
    await expectNoLayoutDefects(page, `SC-V12-05 ustawienia czatu (${name})`)
    await page.keyboard.press('Escape')
    await drawerGone(drawer)
  }
})
