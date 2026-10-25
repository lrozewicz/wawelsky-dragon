// SC-E5-H8z-05 (brief T7 — MAJOR z QA E5-H8z-4): na 390 px rozwinięcie panelu rozmów („>” /
// „Rozwiń panel rozmów”) nie może ściskać kolumny czatu do ~100 px (QA: 9 elementów main z
// right > 391 px, max 452; treść łamie się pionowo, pole pytania nieosiągalne do zwinięcia).
// Po naprawie rozwinięty panel poniżej `md` jest nakładką (szuflada — wzór szuflady ustawień
// czatu), więc kolumna czatu zostaje pełnej szerokości; wybór rozmowy zwija panel. Powyżej `md`
// bez zmian (dwie kolumny — pilnują s18 i visual). Asercje BEZPOŚREDNIE (getBoundingClientRect)
// — czerwone na bazie. Backend nie jest mockowany. Warianty motywu w PĘTLI wewnątrz testu
// (wzór s22): osobne grupy `test.use` to osobne workery, a limiter logowań (10/min, CONTRACT
// E5-2a §4) jest współdzielony przez cały bieg.
import type { APIRequestContext, Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'

import { apiLogin, createChat, deleteAllChats } from './helpers'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

// Logowanie RAZ na plik (T11): limiter logowań jest współdzielony przez cały bieg.
const session = uiSession('s23-mobile-sessions-panel')
test.use({ storageState: session.statePath })
test.setTimeout(180_000)

const API_URL = process.env.WD_E2E_API_URL ?? ''

const MOBILE = { width: 390, height: 844 }
const CHAT_NAME = 'E2E S23 czat mobilny'
// Nazwa rozmowy wyraźnie dłuższa niż panel (280 px) — jak w QA (107 znaków): wielokropek na
// liście i pełna nazwa jako dostępna etykieta przycisku rozmowy.
const LONG_SESSION_NAME =
  'Rozmowa o bardzo długiej nazwie — kontrola nakładki panelu rozmów przy 390 pikselach, ' +
  'wielokropka na liście i przycisku zwinięcia'
// Pytanie dłuższe niż ekran — odpowiedź fake-llm („Odpowiedź testowa: …”) daje wiadomość
// asystenta z paskiem akcji (Kopiuj/👍/👎/Ponów), który na ściśniętej kolumnie wystaje poza okno.
const LONG_QUESTION = 'Opowiedz o Wawelu, smoku wawelskim, katedrze i dzwonie Zygmunt. '.repeat(45)

let tokenPromise: Promise<string> | undefined
function token(request: APIRequestContext): Promise<string> {
  tokenPromise ??= apiLogin(request)
  return tokenPromise
}

let chatIdPromise: Promise<string> | undefined
/** Czat z rozmową — tworzymy raz, leniwie (wzór: memoizacja z s22). */
function chatId(request: APIRequestContext): Promise<string> {
  chatIdPromise ??= token(request).then((auth) => createChat(request, auth, { name: CHAT_NAME }))
  return chatIdPromise
}

let sessionIdPromise: Promise<string> | undefined
/** Rozmowa o długiej nazwie — seed przez API (POST /chats/{id}/sessions, wzór s22). */
function sessionId(request: APIRequestContext): Promise<string> {
  sessionIdPromise ??= (async () => {
    const auth = await token(request)
    const chat = await chatId(request)
    const response = await request.post(`${API_URL}/api/v1/chats/${chat}/sessions`, {
      headers: { authorization: `Bearer ${auth}` },
      data: { name: LONG_SESSION_NAME },
    })
    expect(response.status(), 'POST /api/v1/chats/{id}/sessions (długa nazwa)').toBe(200)
    const body = (await response.json()) as { code: number; data: { id: string }; message?: string }
    expect(body.code, `POST sessions: ${body.message ?? ''}`).toBe(0)
    return body.data.id
  })()
  return sessionIdPromise
}

test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

test.afterEach(async ({ context }) => {
  await session.save(context)
})

test.afterAll(async ({ request }) => {
  // Sprzątanie: czat z rozmową znika z listy dla kolejnych specyfikacji.
  if (chatIdPromise !== undefined) {
    await deleteAllChats(request, await token(request))
  }
})

/** Motyw i viewport PRZED nawigacją — aplikacja czyta je przy renderze (wzór s22). */
async function applyVariant(page: Page, colorScheme: 'dark' | 'light'): Promise<void> {
  await page.setViewportSize(MOBILE)
  await page.emulateMedia({ colorScheme })
}

/**
 * Rozwija panel rozmów i czeka na koniec wejścia (wzór s18/s22: tuż po `toBeVisible` animacja
 * trwa i prostokąty zależą od jej fazy). Szuflada wjeżdża OD LEWEJ, więc koniec slajdu to lewa
 * krawędź na 0 (poll `right ≤ szerokość okna` jest prawdziwy już w połowie animacji). Zwraca
 * panel po `data-testid` — po naprawie rozwinięty panel jest w szufladzie, na bazie rozwija się
 * inline; oba stany rozpoznaje pole wyszukiwania.
 */
async function expandPanel(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: 'Rozwiń panel rozmów' }).click()
  const panel = page.getByTestId('sessions-panel')
  await expect(panel.getByRole('textbox', { name: 'Szukaj w rozmowach' })).toBeVisible()
  await expect
    .poll(async () => {
      const box = await panel.boundingBox()
      return box === null ? Number.POSITIVE_INFINITY : box.x
    })
    .toBeGreaterThanOrEqual(-1)
  return panel
}

/** Elementy `main` (poza panelem rozmów) wystające poza prawą krawędź okna (pomiar z QA). */
async function overflowingMain(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const main = document.querySelector('main')
    if (main === null) throw new Error('brak elementu main')
    const limit = window.innerWidth + 1
    const bad: string[] = []
    for (const el of Array.from(main.querySelectorAll('*'))) {
      if (el.closest('aside[data-testid="sessions-panel"]') !== null) continue
      const rect = el.getBoundingClientRect()
      if (rect.width < 1 || rect.height < 1) continue
      const style = getComputedStyle(el)
      if (style.display === 'none' || style.visibility === 'hidden') continue
      if (rect.right > limit) {
        const id = el.getAttribute('data-testid')
        bad.push(
          `${el.tagName.toLowerCase()}${id ? `[${id}]` : ''} right=${Math.round(rect.right)}`,
        )
      }
    }
    return bad
  })
}

test('SC-E5-H8z-05: rozwinięty panel rozmów na 390 px nakrywa czat, nie ściska go (oba motywy)', async ({
  page,
  request,
}) => {
  const chat = await chatId(request)
  const conversation = await sessionId(request)
  const url = `/chat/${chat}?conversationId=${conversation}`

  // Treść rozmowy raz (motyw domyślny): wymiana daje wiadomość asystenta z paskiem akcji,
  // który na ściśniętej kolumnie wystaje poza prawą krawędź (objaw z QA E5-H8z-4).
  await applyVariant(page, 'light')
  await page.goto(url)
  const input = page.getByPlaceholder('Wpisz pytanie…')
  await expect(input).toBeVisible()
  await input.fill(LONG_QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()
  await expect(page.getByTestId('message-assistant').last()).toContainText('Odpowiedź testowa:', {
    timeout: 60_000,
  })
  // Koniec streamu: przycisk wraca z „Zatrzymaj” na „Wyślij”.
  await expect(page.getByRole('button', { name: 'Wyślij' })).toBeVisible({ timeout: 60_000 })

  for (const variant of [
    { mode: 'ciemny', colorScheme: 'dark' },
    { mode: 'jasny', colorScheme: 'light' },
  ] as const) {
    await applyVariant(page, variant.colorScheme)
    await page.goto(url)
    const input = page.getByPlaceholder('Wpisz pytanie…')
    await expect(input).toBeVisible()
    // Domyślnie (po wejściu) panel zwinięty, jak dziś.
    await expect(page.getByRole('button', { name: 'Rozwiń panel rozmów' })).toBeVisible()

    const panel = await expandPanel(page)

    // (a) Żaden element main poza panelem nie wystaje poza prawą krawędź okna (QA: max 452).
    expect(
      await overflowingMain(page),
      `elementy main poza panelem wystające poza ${MOBILE.width} px (${variant.mode})`,
    ).toEqual([])

    // (a) Kolumna czatu nie jest ściśnięta: nakładka zostawia ją pełnej szerokości.
    const column = page.getByTestId('chat-column')
    await expect(column).toBeVisible()
    const columnBox = await column.boundingBox()
    expect(columnBox, 'kolumna czatu ma obrys').not.toBeNull()
    expect(
      columnBox!.width,
      `kolumna czatu (${Math.round(columnBox!.width)} px) nie jest węższa niż 280 px (${variant.mode})`,
    ).toBeGreaterThanOrEqual(280)

    // (b) Lista rozmów w całości w oknie; przycisk zwinięcia widoczny (klik niżej).
    const panelBox = await panel.boundingBox()
    expect(panelBox, 'panel rozmów ma obrys').not.toBeNull()
    expect(
      panelBox!.x + panelBox!.width,
      `prawa krawędź panelu (${Math.round(panelBox!.x + panelBox!.width)}) ≤ ${MOBILE.width} (${variant.mode})`,
    ).toBeLessThanOrEqual(MOBILE.width + 1)
    const collapse = panel.getByRole('button', { name: 'Zwiń panel rozmów' })
    await expect(collapse).toBeVisible()

    await page.screenshot({ path: `../.task/shots/s23-panel-${variant.mode}-390.png` })

    // (d) Stan rozwinięty bez wad układu.
    await expectNoLayoutDefects(page, `panel rozmów rozwinięty (${variant.mode}, 390)`)

    // (b) Przycisk zwinięcia jest klikalny: panel wraca do paska, pole pytania widoczne.
    // Ukrycie rozwiniętego panelu strzeże pole wyszukiwania (jest tylko w rozwiniętym panelu;
    // pasek zwinięty ma ten sam testid, co szuflada w animacji wyjścia — bez rywalizacji locatora).
    const searchField = page.getByRole('textbox', { name: 'Szukaj w rozmowach' })
    await collapse.click()
    await expect(searchField).toBeHidden()
    await expect(input).toBeVisible()

    // (c) Wybór rozmowy zwija panel i pokazuje czat. `exact` — bez ⋮ („Menu rozmowy …”
    // zawiera nazwę jako podłańcuch).
    await expandPanel(page)
    await panel.getByRole('button', { name: LONG_SESSION_NAME, exact: true }).click()
    await expect(searchField).toBeHidden()
    await expect(input).toBeVisible()

    await page.screenshot({ path: `../.task/shots/s23-wybor-${variant.mode}-390.png` })
    // (d) Stan po zwinięciu bez wad układu (pole pytania przy dole — SC-E5-H8d-06).
    await expectNoLayoutDefects(page, `czat po zwinięciu panelu (${variant.mode}, 390)`)
  }
})
