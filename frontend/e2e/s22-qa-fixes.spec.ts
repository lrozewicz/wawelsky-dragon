// SC-E5-H8z-04 (brief T6 — defekty z QA „pierwszy użytkownik”: E5-H8z-2 C2/C7, E5-H8z-3 D1):
//   (a) Ustawienia → Dostawcy modeli → „Model rerank” z wartością „Brak”: etykieta ma być
//       uniesiona na krawędź pola (jak dla pól z wartością), nie leżeć na tekście „Brak”
//       (zlepek „Brakl rerank” na zrzutach QA; MUI: `displayEmpty` bez `shrink`);
//   (b) lista rozmów czatu: skrócona nazwa z wielokropkiem ma kończyć się PRZED przyciskiem ⋮
//       (≥ 4 px odstępu) — menu nachodziło na koniec nazwy (C7-08-session-row-zoom.png);
//   (c) szuflada „Ustawienia czatu” (390 px): przycisk ✕ w nagłówku (scenariusz SC-E5-H8d-02
//       krok 1: „zamyka ✕ i Esc”), zamyka jak „Anuluj”; Esc nadal zamyka.
// Asercje geometryczne/DOM — czerwone na bazie (TDD); backend nie jest mockowany.
// Warianty (motyw × szerokość) w PĘTLI wewnątrz testów, nie przez `test.use`: osobne grupy
// `test.use` to osobne workery, a każdy robi logowanie przez UI — 8 logowań pod rząd tripi
// limiter logowań (10/min per IP+e-mail, CONTRACT E5-2a §4; biegi na bazie padały na 7. workerze).
import type { APIRequestContext } from '@playwright/test'

import { expect, test } from './fixtures'

import { apiLogin, createChat, deleteAllChats } from './helpers'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

// Logowanie RAZ na plik (T11): limiter logowań jest współdzielony przez cały bieg.
const session = uiSession('s22-qa-fixes')
test.use({ storageState: session.statePath })
test.setTimeout(120_000)

const API_URL = process.env.WD_E2E_API_URL ?? ''

// Nazwa rozmowy wyraźnie dłuższa niż kolumna panelu (280 px) — wielokropek pewny.
const LONG_SESSION_NAME =
  'Rozmowa testowa o bardzo długiej nazwie — weryfikacja wielokropka i odstępu od przycisku menu rozmowy'

type Variant = { mode: 'ciemny' | 'jasny'; colorScheme: 'dark' | 'light'; width: number }

const VARIANTS: Variant[] = [
  { mode: 'ciemny', colorScheme: 'dark', width: 1280 },
  { mode: 'ciemny', colorScheme: 'dark', width: 390 },
  { mode: 'jasny', colorScheme: 'light', width: 1280 },
  { mode: 'jasny', colorScheme: 'light', width: 390 },
]

/** Ustawia wariant PRZED nawigacją: motyw i viewport czyta aplikacja przy renderze strony. */
async function applyVariant(
  page: import('@playwright/test').Page,
  variant: Variant,
): Promise<void> {
  await page.setViewportSize({
    width: variant.width,
    height: variant.width === 1280 ? 800 : 844,
  })
  await page.emulateMedia({ colorScheme: variant.colorScheme })
}

let tokenPromise: Promise<string> | undefined
function token(request: APIRequestContext): Promise<string> {
  tokenPromise ??= apiLogin(request)
  return tokenPromise
}

let chatIdPromise: Promise<string> | undefined
/** Czat dla punktów (b) i (c) — tworzymy raz, leniwie (wzór: memoizacja z s21). */
function chatId(request: APIRequestContext): Promise<string> {
  chatIdPromise ??= token(request).then((auth) =>
    createChat(request, auth, { name: 's22 — czat QA' }),
  )
  return chatIdPromise
}

let longSessionPromise: Promise<void> | undefined
/** Sesja (rozmowa) o długiej nazwie — raz na plik (dwa warianty motywu punktu (b)). */
function longSession(request: APIRequestContext): Promise<void> {
  longSessionPromise ??= (async () => {
    const auth = await token(request)
    const chat = await chatId(request)
    const response = await request.post(`${API_URL}/api/v1/chats/${chat}/sessions`, {
      headers: { authorization: `Bearer ${auth}` },
      data: { name: LONG_SESSION_NAME },
    })
    expect(response.status(), 'POST /api/v1/chats/{id}/sessions (długa nazwa)').toBe(200)
    const body = (await response.json()) as { code: number; message?: string }
    expect(body.code, `POST sessions: ${body.message ?? ''}`).toBe(0)
  })()
  return longSessionPromise
}

test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

test.afterEach(async ({ context }) => {
  await session.save(context)
})

test.afterAll(async ({ request }) => {
  // Sprzątanie: czat z punktów (b)/(c) znika z listy dla kolejnych specyfikacji.
  if (chatIdPromise !== undefined) {
    await deleteAllChats(request, await token(request))
  }
})

test('SC-E5-H8z-04 (a) etykieta „Model rerank” przy „Brak” uniesiona, bez nachodzenia (1280 i 390, oba motywy)', async ({
  page,
}) => {
  for (const variant of VARIANTS) {
    await applyVariant(page, variant)
    await page.goto('/user-setting/model')
    const field = page.getByTestId('defaults-rerank')
    await expect(field).toBeVisible()
    // Stos testowy ma domyślnie ustawiony rerank (seed K9: fake-rerank) — pole startuje
    // z wartością, więc wybieramy „Brak” wprost (stan z QA na instalacji produkcyjnej).
    await expect(field.locator('.MuiSelect-select')).toContainText(/fake-/)
    await field.click()
    await page.getByRole('option', { name: 'Brak' }).click()
    await expect(field.locator('.MuiSelect-select')).toHaveText('Brak')

    // Odebranie fokusu: przy wartości pustej etykieta ma zostać uniesiona (jak przy polu
    // z wartością), a nie wracać do pozycji spoczynkowej na tekście „Brak”.
    await page.getByRole('heading', { name: 'Modele domyślne' }).click()

    const label = field.locator('.MuiInputLabel-root')
    await expect(label).toBeVisible()
    // Sedno defektu C2/D2: etykieta w pozycji spoczynkowej (data-shrink=false) na wartości.
    // UWAGA: w MUI v9 etykieta Selecta to DIV (component: 'div'), nie element `label`.
    await expect(label).toHaveAttribute('data-shrink', 'true')

    // Koniec animacji etykiety MUI (~150 ms) przed pomiarem — pozycja spoczynkowa jest
    // osiągana płynnie, a pomiar w trakcie daje losowe prostokąty.
    await page.waitForTimeout(400)

    const boxes = await field.evaluate((root) => {
      const labelEl = root.querySelector('.MuiInputLabel-root')
      const outEl = root.querySelector('.MuiOutlinedInput-root')
      const valueEl = root.querySelector('.MuiSelect-select')
      if (labelEl === null || outEl === null || valueEl === null) {
        throw new Error('brak etykiety, obrysu pola albo wyświetlonej wartości')
      }
      const rect = (el: Element) => {
        const r = el.getBoundingClientRect()
        return { top: r.top, bottom: r.bottom, left: r.left, right: r.right }
      }
      const node = valueEl.firstChild
      if (node === null || node.nodeType !== Node.TEXT_NODE) {
        throw new Error('wartość pola nie jest węzłem tekstowym')
      }
      const range = document.createRange()
      range.selectNodeContents(node)
      const glyph = range.getClientRects()[0]
      if (glyph === undefined) throw new Error('brak prostokąta glifów wartości')
      return {
        label: rect(labelEl),
        field: rect(outEl),
        glyph: {
          top: glyph.top,
          bottom: glyph.bottom,
          left: glyph.left,
          right: glyph.right,
        },
      }
    })
    expect(
      boxes.label.bottom,
      `etykieta nad górną krawędzią pola (${variant.mode}, ${variant.width}): ` +
        `label.bottom (${boxes.label.bottom}) ≤ field.top + 12 (${boxes.field.top + 12})`,
    ).toBeLessThanOrEqual(boxes.field.top + 12)
    expect(
      boxes.label.bottom,
      `etykieta w całości nad tekstem „Brak” (${variant.mode}, ${variant.width}): ` +
        `label.bottom (${boxes.label.bottom}) ≤ glyph.top (${boxes.glyph.top})`,
    ).toBeLessThanOrEqual(boxes.glyph.top + 1)

    await field.scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `../.task/shots/s22-rerank-${variant.mode}-${variant.width}.png`,
    })
  }

  await expectNoLayoutDefects(page, 'Modele domyślne, „Model rerank” = Brak (ostatni wariant)')
})

test('SC-E5-H8z-04 (b) nazwa rozmowy kończy się przed ⋮ z odstępem ≥ 4 px (1280, oba motywy)', async ({
  page,
  request,
}) => {
  const chat = await chatId(request)
  await longSession(request)

  for (const variant of [
    { mode: 'ciemny', colorScheme: 'dark' },
    { mode: 'jasny', colorScheme: 'light' },
  ] as const) {
    await applyVariant(page, { ...variant, width: 1280 })
    await page.goto(`/chat/${chat}`)
    const panel = page.getByTestId('sessions-panel')
    const name = panel.locator('.MuiListItemText-primary')
    await expect(name).toHaveText(LONG_SESSION_NAME)
    const menu = panel.getByRole('button', { name: `Menu rozmowy ${LONG_SESSION_NAME}` })
    await expect(menu).toBeVisible()

    const boxes = await panel.evaluate((root) => {
      const nameEl = root.querySelector('.MuiListItemText-primary')
      const buttons = [...root.querySelectorAll('button')]
      const menuEl = buttons.find((button) =>
        (button.getAttribute('aria-label') ?? '').includes('Menu rozmowy'),
      )
      if (nameEl === null || menuEl === undefined) {
        throw new Error('brak nazwy rozmowy albo przycisku menu ⋮')
      }
      return {
        nameRight: nameEl.getBoundingClientRect().right,
        menuLeft: menuEl.getBoundingClientRect().left,
      }
    })
    expect(
      boxes.nameRight,
      `nazwa kończy się przed ⋮ z odstępem ≥ 4 px (${variant.mode}): ` +
        `name.right (${boxes.nameRight}) ≤ menu.left − 4 (${boxes.menuLeft - 4})`,
    ).toBeLessThanOrEqual(boxes.menuLeft - 4)

    await page.screenshot({
      path: `../.task/shots/s22-rozmowy-${variant.mode}-1280.png`,
    })
  }

  await expectNoLayoutDefects(page, 'lista rozmów, długa nazwa (ostatni wariant)')
})

test('SC-E5-H8z-04 (c) szuflada „Ustawienia czatu” zamykana ✕ i Esc (390, oba motywy)', async ({
  page,
  request,
}) => {
  const chat = await chatId(request)

  for (const variant of [
    { mode: 'ciemny', colorScheme: 'dark' },
    { mode: 'jasny', colorScheme: 'light' },
  ] as const) {
    await applyVariant(page, { ...variant, width: 390 })
    await page.goto(`/chat/${chat}`)
    await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
    const drawer = page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia czatu' })
    await expect(drawer).toBeVisible()

    // Koniec animacji wejścia MUI Slide przed pomiarem i zrzutem (wzór: s18): tuż po
    // `toBeVisible` slajd trwa i prawa krawędź szuflady (z ✕) jest jeszcze poza oknem.
    const viewportWidth = page.viewportSize()?.width ?? 0
    await expect
      .poll(async () => {
        const box = await drawer.boundingBox()
        return box === null ? Number.POSITIVE_INFINITY : box.x + box.width
      })
      .toBeLessThanOrEqual(viewportWidth)

    // Sedno defektu D1 (SC-E5-H8d-02: „zamyka ✕ i Esc”): w nagłówku jest ✕.
    const close = drawer.getByRole('button', { name: /Zamknij|Close/ })
    await expect(close).toBeVisible()

    // Ikona nie nachodzi na zakładki: cała nad listą zakładek.
    const tabs = drawer.getByRole('tablist')
    await expect(tabs).toBeVisible()
    const edges = await drawer.evaluate((root) => {
      const closeEl = [...root.querySelectorAll('button')].find((button) =>
        /Zamknij|Close/.test(button.getAttribute('aria-label') ?? ''),
      )
      const tabsEl = root.querySelector('[role="tablist"]')
      if (closeEl === undefined || tabsEl === null) {
        throw new Error('brak przycisku „Zamknij” albo zakładek')
      }
      return {
        closeBottom: closeEl.getBoundingClientRect().bottom,
        tabsTop: tabsEl.getBoundingClientRect().top,
      }
    })
    expect(
      edges.closeBottom,
      `✕ w całości nad zakładkami (${variant.mode}): close.bottom (${edges.closeBottom}) ≤ tabs.top (${edges.tabsTop})`,
    ).toBeLessThanOrEqual(edges.tabsTop + 1)

    await page.screenshot({
      path: `../.task/shots/s22-szuflada-${variant.mode}-390.png`,
    })

    await close.click()
    await expect(drawer).toBeHidden()

    // Esc nadal zamyka (wariant scenariusza SC-E5-H8d-02).
    await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
    await expect(drawer).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(drawer).toBeHidden()

    await expectNoLayoutDefects(page, `szuflada ustawień czatu z ✕ (${variant.mode}, 390)`)
  }
})
