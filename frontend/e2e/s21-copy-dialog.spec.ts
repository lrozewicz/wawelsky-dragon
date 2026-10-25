// SC-E6-2-06 (QA-UI E6-2-2, defekt MAJOR): dialog nowego klucza API — klik „Kopiuj token”
// na stosie HTTP (brak `navigator.clipboard`) ma realnie skopiować pełny token przez fallback
// `execCommand('copy')`. Przed poprawką fallback doklejał `textarea` do `document.body`, a focus
// trap dialogu MUI zabierał jej fokus — `execCommand` wołał się przy PUSTYM zaznaczeniu, schowek
// zostawał bez zmian, a UI pokazywał „Skopiowano”. Warianty: 1440 px, 390 px i porażka
// `execCommand` (czytelny błąd zamiast fałszywego sukcesu). Odzew kopiowania z tabeli (Snackbar)
// pilnuje MINOR z tego samego przebiegu. Błędy konsoli pilnuje fixture `page` (`./fixtures`).
import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin } from './helpers'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'

// Logowanie RAZ na plik (E5-H8c T11) — wzór: s20-mcp-card.spec.ts.
const session = uiSession('s21-copy-dialog')
test.use({
  storageState: session.statePath,
})
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

/** Współdzielony token admina na cały bieg pliku (jeden `apiLogin` — limiter logowań). */
let adminTokenPromise: Promise<string> | undefined
function adminToken(request: Parameters<typeof apiLogin>[0]): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

const API_URL = process.env.WD_E2E_API_URL ?? ''

/** Maska tokenu na liście kluczy (kontrakt E3-6c1 §2), jak w s09. */
function maskedToken(token: string): string {
  return `${token.slice(0, 12)}…${token.slice(-4)}`
}

/** Tekst zapamiętany przy kopiowaniu przez fallback (spy na `execCommand`, patrz niżej). */
function copiedText(page: Page): Promise<string> {
  return page.evaluate(() => (window as unknown as { __copiedText?: string }).__copiedText ?? '')
}

type InitScript = Parameters<Page['addInitScript']>[0]

/**
 * Stos testowy działa po HTTP (`host.docker.internal`), więc `navigator.clipboard` nie istnieje
 * — klik „Kopiuj token” przechodzi przez fallback `document.execCommand('copy')`. Init-script
 * owija `execCommand`: przy kopiowaniu zapamiętuje ZAZNACZONY tekst (to jest sedno defektu —
 * przed poprawką pusty), żeby test sprawdził kontrakt „klik → schowek dostaje pełny token”.
 * Prawdziwe `execCommand` dalej się wykonuje, więc udana kopia pokazuje też „Skopiowano”.
 */
function execCommandCopySpy(): InitScript {
  return () => {
    const original = document.execCommand.bind(document)
    ;(window as unknown as { __copiedText?: string }).__copiedText = ''
    document.execCommand = ((commandId: string, ...rest: unknown[]) => {
      if (commandId === 'copy') {
        ;(window as unknown as { __copiedText?: string }).__copiedText =
          document.getSelection()?.toString() ?? ''
      }
      return (original as (...args: unknown[]) => boolean)(commandId, ...rest)
    }) as typeof document.execCommand
  }
}

/** Init-script porażki: `execCommand('copy')` zwraca false (przeglądarka odmówiła kopii). */
function execCommandCopyFailure(): InitScript {
  return () => {
    document.execCommand = ((commandId: string) =>
      commandId !== 'copy') as typeof document.execCommand
  }
}

/** Wejście na Klucze API z pinezką init-scriptu (każdy test zaczyna od `goto`). */
async function openApiKeys(page: Page, path = '/user-setting/api', init = execCommandCopySpy()) {
  await page.addInitScript(init)
  await page.goto(path)
}

/** Ścieżka użytkownika: nawigacja → Ustawienia → zakładka Klucze API (nie bezpośredni adres).
 *  Z pinezką spy jak w `openApiKeys` — inaczej `copiedText` zostaje puste też przy udanej kopii. */
async function openApiKeysViaUi(page: Page): Promise<void> {
  await page.addInitScript(execCommandCopySpy())
  await page.goto('/')
  await page.getByRole('navigation').getByRole('link', { name: 'Ustawienia' }).click()
  await page.getByTestId('settings-tab-api').click()
  await expect(page).toHaveURL(/\/user-setting\/api$/)
}

/** Tworzy klucz w dialogu przez UI i zwraca pełny token z widoku sekretu. */
async function createKeyInDialog(page: Page): Promise<string> {
  await page.getByRole('button', { name: 'Utwórz klucz' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Utwórz', exact: true }).click()
  const field = dialog.getByTestId('settings-new-token')
  await expect(field).toBeVisible()
  const token = ((await field.textContent()) ?? '').trim()
  expect(token, 'pełny token musi zaczynać się od „ragflow-”').toMatch(/^ragflow-/)
  return token
}

/** Zamyka dialog po skopiowaniu (sekret znika z DOM — pełny token tylko w schowku). */
async function closeKeyDialog(page: Page): Promise<void> {
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Zamknij', exact: true }).click()
  await expect(dialog).toHaveCount(0)
}

test.describe('SC-E6-2-06 kopiowanie tokenu w dialogu nowego klucza', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('SC-E6-2-06: schowek dostaje pełny token (spy na execCommand), odzew także z tabeli', async ({
    page,
    request,
  }) => {
    // Klucz sprząta WYŁĄCZNIE `finally` (DELETE także po zielonym przebiegu, brief T9) —
    // wzór s09 z `key = null` po usunięciu przez UI tu nie obowiązuje: żaden test nie kasuje
    // klucza sam, więc ustawienie `null` zostawiałoby go w bazie do następnego resetu.
    let key: string | null = null
    try {
      await openApiKeysViaUi(page)
      key = await createKeyInDialog(page)
      await expectNoLayoutDefects(page, 'dialog nowego klucza (SC-E6-2-06, 1440 px)')

      const dialog = page.getByRole('dialog')
      await dialog.getByRole('button', { name: 'Kopiuj token' }).click()

      // Sedno defektu: ZAZNACZONY tekst w chwili `execCommand('copy')` = pełny token widoczny
      // w dialogu (przed poprawką spy logował pusty tekst, choć UI pokazywał „Skopiowano”).
      expect(await copiedText(page)).toBe(key)
      await expect(dialog.getByRole('button', { name: 'Skopiowano' })).toBeVisible()

      // MINOR z QA-UI E6-2-2: kopiowanie istniejącego tokenu z tabeli ma widoczny odzew.
      await closeKeyDialog(page)
      await page.getByRole('button', { name: `Kopiuj token ${maskedToken(key)}` }).click()
      await expect(page.getByTestId('keys-copy-snackbar')).toBeVisible()
      await expect(page.getByTestId('keys-copy-snackbar')).toContainText('Skopiowano')
      expect(await copiedText(page)).toBe(key)
    } finally {
      if (key !== null) {
        const response = await request.delete(`${API_URL}/api/v1/system/tokens/${key}`, {
          headers: { authorization: `Bearer ${await adminToken(request)}` },
        })
        expect(response.status(), 'DELETE /api/v1/system/tokens/{token}').toBe(200)
      }
    }
  })

  test('SC-E6-2-06 porażka (execCommand=false): czytelny błąd, token zaznaczony do ręcznej kopii', async ({
    page,
    request,
  }) => {
    let key: string | null = null
    try {
      await openApiKeys(page, '/user-setting/api', execCommandCopyFailure())
      key = await createKeyInDialog(page)

      const dialog = page.getByRole('dialog')
      await dialog.getByRole('button', { name: 'Kopiuj token' }).click()

      // Fałszywe „Skopiowano” jest zabronione: porażka = komunikat błędu i zaznaczony token.
      await expect(dialog.getByTestId('settings-copy-error')).toBeVisible()
      await expect(dialog.getByTestId('settings-copy-error')).toContainText(
        'Nie udało się skopiować',
      )
      await expect(dialog.getByRole('button', { name: 'Kopiuj token' })).toBeVisible()
      await expect(dialog.getByRole('button', { name: 'Kopiuj token' })).not.toContainText(
        'Skopiowano',
      )
      expect(await page.evaluate(() => document.getSelection()?.toString())).toBe(key)
    } finally {
      if (key !== null) {
        const response = await request.delete(`${API_URL}/api/v1/system/tokens/${key}`, {
          headers: { authorization: `Bearer ${await adminToken(request)}` },
        })
        expect(response.status(), 'DELETE /api/v1/system/tokens/{token}').toBe(200)
      }
    }
  })
})

/**
 * Kontrast komunikatu porażki kopiowania (defekt MAJOR z QA-UI E6-2-3): w ciemnym motywie
 * `color="error"` dawał `error.main` = rgb(145,8,8) na tle alertu rgba(59,45,2,0.5) — 1,44:1
 * z pomiaru QA. WCAG 2.x AA: ≥ 4,5:1 w OBU motywach i we WSZYSTKICH miejscach renderowania
 * (dialog nowego klucza + karty „API serwera” i „Serwer MCP” — ta sama strona).
 */
type Rgb = readonly [number, number, number]

/** Składowa liniowa sRGB i luminancja wg WCAG 2.x (wzór: src/theme/contrast.test.ts). */
function linear(channel: number): number {
  const c = channel / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

function relativeLuminance(rgb: Rgb): number {
  return 0.2126 * linear(rgb[0]) + 0.7152 * linear(rgb[1]) + 0.0722 * linear(rgb[2])
}

function contrastRatio(foreground: Rgb, background: Rgb): number {
  const fgLuminance = relativeLuminance(foreground)
  const bgLuminance = relativeLuminance(background)
  const lighter = Math.max(fgLuminance, bgLuminance)
  const darker = Math.min(fgLuminance, bgLuminance)
  return (lighter + 0.05) / (darker + 0.05)
}

/** Kolor tekstu elementu (getComputedStyle → rgb składowe). */
function textColor(page: Page, selector: string): Promise<Rgb> {
  return page.evaluate((sel: string): Rgb => {
    const el = document.querySelector(sel)
    if (el === null) throw new Error(`brak elementu: ${sel}`)
    const match = /rgba?\(([^)]+)\)/.exec(getComputedStyle(el).color)
    if (match === null || match[1] === undefined)
      throw new Error(`nieczytelny kolor tekstu: ${sel}`)
    const parts = match[1].split(/[\s,/]+/).map(Number)
    return [parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0]
  }, selector)
}

/**
 * Efektywne tło elementu: warstwy `backgroundColor` od elementu w górę, zeskomponowane
 * do nieprzezroczystości jak w CSS; niedomkniętą przezroczystość domyka białe płótno.
 */
function effectiveBackground(page: Page, selector: string): Promise<Rgb> {
  return page.evaluate((sel: string): Rgb => {
    const el = document.querySelector(sel)
    if (el === null) throw new Error(`brak elementu: ${sel}`)
    const layers: [number, number, number, number][] = []
    for (let node: Element | null = el; node !== null; node = node.parentElement) {
      const match = /rgba?\(([^)]+)\)/.exec(getComputedStyle(node).backgroundColor)
      if (match === null || match[1] === undefined) continue
      const parts = match[1].split(/[\s,/]+/).map(Number)
      const alpha = parts.length > 3 ? (parts[3] ?? 1) : 1
      layers.push([parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0, alpha])
      if (alpha >= 1) break
    }
    const bottom = layers[layers.length - 1]
    if (bottom === undefined) return [255, 255, 255]
    let [r, g, b, a] = bottom
    for (let i = layers.length - 2; i >= 0; i--) {
      const layer = layers[i]
      if (layer === undefined) break
      const [tr, tg, tb, ta] = layer
      r = tr * ta + r * (1 - ta)
      g = tg * ta + g * (1 - ta)
      b = tb * ta + b * (1 - ta)
      a = ta + a * (1 - ta)
    }
    return [
      Math.round(r * a + 255 * (1 - a)),
      Math.round(g * a + 255 * (1 - a)),
      Math.round(b * a + 255 * (1 - a)),
    ]
  }, selector)
}

async function measuredContrast(page: Page, selector: string): Promise<number> {
  const [foreground, background] = await Promise.all([
    textColor(page, selector),
    effectiveBackground(page, selector),
  ])
  return contrastRatio(foreground, background)
}

test.describe('SC-E6-2-06 kontrast komunikatu porażki kopiowania (QA-UI E6-2-3 MAJOR)', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test.describe('ciemny motyw', () => {
    test.use({ colorScheme: 'dark' })

    test('ciemny motyw 1440: kontrast błędu ≥ 4,5:1 w dialogu i na kartach', async ({
      page,
      request,
    }) => {
      let key: string | null = null
      try {
        await openApiKeys(page, '/user-setting/api', execCommandCopyFailure())
        key = await createKeyInDialog(page)

        const dialog = page.getByRole('dialog')
        await dialog.getByRole('button', { name: 'Kopiuj token' }).click()
        await expect(dialog.getByTestId('settings-copy-error')).toBeVisible()
        await expectNoLayoutDefects(page, 'dialog — porażka kopiowania (ciemny motyw, 1440 px)')
        const dialogContrast = await measuredContrast(page, '[data-testid="settings-copy-error"]')
        expect(
          dialogContrast,
          'dialog nowego klucza — kontrast tekstu błędu',
        ).toBeGreaterThanOrEqual(4.5)

        // Pozostałe miejsca renderowania komunikatu — karty pod spodem, ta sama strona.
        await closeKeyDialog(page)
        await page.getByRole('button', { name: 'Kopiuj adres API' }).click()
        await expect(page.getByTestId('api-url-error')).toBeVisible()
        expect(
          await measuredContrast(page, '[data-testid="api-url-error"]'),
          'karta „API serwera” — kontrast tekstu błędu',
        ).toBeGreaterThanOrEqual(4.5)

        await page.getByRole('button', { name: 'Kopiuj adres MCP' }).click()
        await expect(page.getByTestId('mcp-error-http')).toBeVisible()
        expect(
          await measuredContrast(page, '[data-testid="mcp-error-http"]'),
          'karta „Serwer MCP” — kontrast tekstu błędu',
        ).toBeGreaterThanOrEqual(4.5)
      } finally {
        if (key !== null) {
          const response = await request.delete(`${API_URL}/api/v1/system/tokens/${key}`, {
            headers: { authorization: `Bearer ${await adminToken(request)}` },
          })
          expect(response.status(), 'DELETE /api/v1/system/tokens/{token}').toBe(200)
        }
      }
    })
  })

  test.describe('jasny motyw', () => {
    test.use({ colorScheme: 'light' })

    test('jasny motyw 1440: brak regresji, kontrast błędu w dialogu ≥ 4,5:1', async ({
      page,
      request,
    }) => {
      let key: string | null = null
      try {
        await openApiKeys(page, '/user-setting/api', execCommandCopyFailure())
        key = await createKeyInDialog(page)

        const dialog = page.getByRole('dialog')
        await dialog.getByRole('button', { name: 'Kopiuj token' }).click()
        await expect(dialog.getByTestId('settings-copy-error')).toBeVisible()
        expect(
          await measuredContrast(page, '[data-testid="settings-copy-error"]'),
          'dialog nowego klucza — kontrast tekstu błędu',
        ).toBeGreaterThanOrEqual(4.5)
      } finally {
        if (key !== null) {
          const response = await request.delete(`${API_URL}/api/v1/system/tokens/${key}`, {
            headers: { authorization: `Bearer ${await adminToken(request)}` },
          })
          expect(response.status(), 'DELETE /api/v1/system/tokens/{token}').toBe(200)
        }
      }
    })
  })
})

test.describe('SC-E6-2-06 kopiowanie tokenu 390 px', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('SC-E6-2-06: schowek dostaje pełny token także na wąskim ekranie', async ({
    page,
    request,
  }) => {
    let key: string | null = null
    try {
      await openApiKeys(page)
      key = await createKeyInDialog(page)

      const dialog = page.getByRole('dialog')
      await dialog.getByRole('button', { name: 'Kopiuj token' }).click()
      expect(await copiedText(page)).toBe(key)
      await expect(dialog.getByRole('button', { name: 'Skopiowano' })).toBeVisible()

      await expectNoLayoutDefects(page, 'dialog nowego klucza (SC-E6-2-06, 390 px)')
    } finally {
      if (key !== null) {
        const response = await request.delete(`${API_URL}/api/v1/system/tokens/${key}`, {
          headers: { authorization: `Bearer ${await adminToken(request)}` },
        })
        expect(response.status(), 'DELETE /api/v1/system/tokens/{token}').toBe(200)
      }
    }
  })

  test('SC-E6-2-06 porażka 390 px: komunikat błędu czytelny na wąskim ekranie', async ({
    page,
    request,
  }) => {
    let key: string | null = null
    try {
      await openApiKeys(page, '/user-setting/api', execCommandCopyFailure())
      key = await createKeyInDialog(page)

      const dialog = page.getByRole('dialog')
      await dialog.getByRole('button', { name: 'Kopiuj token' }).click()
      await expect(dialog.getByTestId('settings-copy-error')).toBeVisible()
      await expect(dialog.getByRole('button', { name: 'Kopiuj token' })).not.toContainText(
        'Skopiowano',
      )

      await expectNoLayoutDefects(page, 'dialog nowego klucza — porażka (SC-E6-2-06, 390 px)')
    } finally {
      if (key !== null) {
        const response = await request.delete(`${API_URL}/api/v1/system/tokens/${key}`, {
          headers: { authorization: `Bearer ${await adminToken(request)}` },
        })
        expect(response.status(), 'DELETE /api/v1/system/tokens/{token}').toBe(200)
      }
    }
  })
})
