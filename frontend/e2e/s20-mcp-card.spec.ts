// Scenariusz SC-E6-2-06 (work/wp/E6-2/SCENARIOS.md, brief E6-2 T4): zalogowany użytkownik
// otwiera Ustawienia → Klucze API i widzi kartę „Serwer MCP" — adresy transportów z origin
// strony, kopiowanie każdego z nich do schowka, przykład konfiguracji klienta z placeholderem
// klucza (nigdy prawdziwy klucz). Warianty: 1440 px, 390 px (brak poziomego przewijania
// strony), ciemny motyw, EN. Błędy konsoli pilnuje fixture `page` (`./fixtures`).
import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin } from './helpers'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

// Logowanie RAZ na plik (E5-H8c T11): limiter logowań liczy KAŻDĄ próbę (10/min per IP+e-mail,
// CONTRACT E5-2a §4). Testy startują z sesją z `storageState`; `afterEach` zapisuje stan po
// rotacji cookie. Uprawnień schowka nie nadajemy: stos testowy działa po HTTP, `navigator.clipboard`
// nie istnieje, a ścieżka kopiowania to fallback `execCommand` (brief E6-2 T7); wariant ze schowkiem
// asynchronicznym (secure context) pilnuje vitest (`copyToClipboard.test.ts`).
const session = uiSession('s20-mcp-card')
test.use({
  storageState: session.statePath,
})
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context, request }) => {
  await session.save(context)
  // EN-test zmienia język profilu przez API — przywracamy pl dla pozostałych plików biegu.
  const token = await adminToken(request)
  await setProfileLanguage(request, token, 'pl')
})

/** Współdzielony token admina na cały bieg pliku (jeden `apiLogin` — limiter logowań). */
let adminTokenPromise: Promise<string> | undefined
function adminToken(request: Parameters<typeof apiLogin>[0]): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

/** Ścieżka użytkownika ze scenariusza: Ustawienia → zakładka Klucze API (nie bezpośredni adres). */
async function openApiKeysViaUi(page: Page): Promise<void> {
  await openApiKeys(page)
  await page.getByRole('navigation').getByRole('link', { name: 'Ustawienia' }).click()
  await page.getByTestId('settings-tab-api').click()
  await expect(page).toHaveURL(/\/user-setting\/api$/)
}

/** Tekst zapamiętany przy kopiowaniu przez fallback (spy na `execCommand`, patrz niżej). */
function copiedText(page: Page): Promise<string> {
  return page.evaluate(() => (window as unknown as { __copiedText?: string }).__copiedText ?? '')
}

type InitScript = Parameters<Page['addInitScript']>[0]

/**
 * Stos testowy działa po HTTP (`host.docker.internal`), więc `navigator.clipboard` nie istnieje
 * (secure context; prod po TLS ma go natywnie) — klik „Kopiuj” przechodzi przez fallback
 * `document.execCommand('copy')` (brief E6-2 T7). Init-script owija `execCommand`: przy
 * kopiowaniu zapamiętuje ZAZNACZONY tekst, żeby test sprawdził kontrakt „klik → schowek dostaje
 * pełny adres/przykład” bez prawdziwego schowka. Prawdziwe `execCommand` dalej się wykonuje,
 * więc udana kopia pokazuje też znacznik „Skopiowano”.
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
async function openApiKeys(page: Page, path = '/', init = execCommandCopySpy()): Promise<void> {
  await page.addInitScript(init)
  await page.goto(path)
}

/** Origin strony widziany przez przeglądarkę (adresy MCP są liczone z origin, kontrakt K17). */
function pageOrigin(page: Page): Promise<string> {
  return page.evaluate(() => window.location.origin)
}

/** Przykład konfiguracji z karty (tekst bloku `pre`). */
async function exampleText(page: Page): Promise<string> {
  return (await page.getByTestId('mcp-example').textContent()) ?? ''
}

test.describe('SC-E6-2-06 karta „Serwer MCP"', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('SC-E6-2-06: adresy z origin, kopiowanie, przykład bez prawdziwego klucza', async ({
    page,
  }) => {
    await openApiKeysViaUi(page)
    const origin = await pageOrigin(page)

    const card = page.getByTestId('mcp-card')
    await expect(card).toBeVisible()
    await expect(card.getByRole('heading', { name: 'Serwer MCP' })).toBeVisible()

    // Adresy transportów: origin strony + /mcp i /sse.
    await expect(card.getByTestId('mcp-url-http')).toHaveText(`${origin}/mcp`)
    await expect(card.getByTestId('mcp-url-sse')).toHaveText(`${origin}/sse`)

    // Kopiowanie każdego adresu: schowek dostaje PEŁNY adres, znacznik „Skopiowano".
    await card.getByTestId('mcp-copy-http').click()
    expect(await copiedText(page)).toBe(`${origin}/mcp`)
    await expect(card.getByTestId('mcp-copy-http')).toContainText('Skopiowano')

    await card.getByTestId('mcp-copy-sse').click()
    expect(await copiedText(page)).toBe(`${origin}/sse`)

    // Przykład konfiguracji klienta: placeholder klucza, nigdy ciąg wyglądający na klucz
    // (`wd_…` z admin-API albo `ragflow-…` z Kluczy API — format z `ApiKeysPage`).
    const example = await exampleText(page)
    expect(example).toContain(`"url": "${origin}/mcp"`)
    expect(example).toContain('Bearer <TWÓJ_KLUCZ_API>')
    expect(example, 'przykład nie może zawierać klucza').not.toMatch(/wd_[A-Za-z0-9]{16,}/)
    expect(example).not.toContain('ragflow-')

    await card.getByTestId('mcp-copy-example').click()
    expect(await copiedText(page)).toBe(example)

    await expectNoLayoutDefects(page, 'karta „Serwer MCP" (SC-E6-2-06, 1440 px)')
  })
})

test.describe('SC-E6-2-06 wariant 390 px', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('SC-E6-2-06: bloki pod sobą, kopiowanie działa, brak poziomego przewijania strony', async ({
    page,
  }) => {
    await openApiKeys(page, '/user-setting/api')
    const card = page.getByTestId('mcp-card')
    await expect(card).toBeVisible()

    // Brak poziomego przewijania CAŁEJ strony (przykład JSON przewija się wewnątrz ramki).
    const widths = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      inner: window.innerWidth,
    }))
    expect(
      widths.scroll,
      `scrollWidth ${widths.scroll} vs okno ${widths.inner}`,
    ).toBeLessThanOrEqual(widths.inner)

    // Przyciski kopiowania zawsze widoczne; schowek dostaje pełny adres także na wąskim ekranie.
    for (const testId of ['mcp-copy-http', 'mcp-copy-sse', 'mcp-copy-example']) {
      await expect(card.getByTestId(testId)).toBeVisible()
    }
    await card.getByTestId('mcp-copy-sse').click()
    expect(await copiedText(page)).toBe(`${await pageOrigin(page)}/sse`)

    await expectNoLayoutDefects(page, 'karta „Serwer MCP" (SC-E6-2-06, 390 px)')
  })
})

test.describe('SC-E6-2-06 wariant ciemny', () => {
  test.use({ colorScheme: 'dark' })

  test('SC-E6-2-06: karta czytelna w ciemnym motywie (tokeny MUI, kontrast U9)', async ({
    page,
  }) => {
    await openApiKeys(page, '/user-setting/api')
    const card = page.getByTestId('mcp-card')
    await expect(card).toBeVisible()
    await expect(card.getByRole('heading', { name: 'Serwer MCP' })).toBeVisible()
    await expect(card.getByTestId('mcp-example')).toBeVisible()

    // Blok przykładu ma własne tło z tokena motywu (widoczne na tle karty) i pełną nieprzezroczystość.
    const exampleStyle = await card.getByTestId('mcp-example').evaluate((el) => {
      const style = getComputedStyle(el)
      return { backgroundColor: style.backgroundColor, opacity: style.opacity }
    })
    expect(exampleStyle.opacity).toBe('1')
    expect(exampleStyle.backgroundColor).not.toBe('rgba(0, 0, 0, 0)')

    await expectNoLayoutDefects(page, 'karta „Serwer MCP" (SC-E6-2-06, ciemny motyw)')
  })
})

test('SC-E6-2-06 wariant EN: „Server (MCP)", przykład z <YOUR_API_KEY>', async ({
  page,
  request,
}) => {
  // Profil admina nadpisuje locale przeglądarki po zalogowaniu (authState.applyUser), więc
  // wariant EN ustawia język profilu przez API, nie sam `locale` (wzór: s17-model-edit).
  const token = await adminToken(request)
  await setProfileLanguage(request, token, 'en')

  await openApiKeys(page, '/user-setting/api')
  const card = page.getByTestId('mcp-card')
  await expect(card.getByRole('heading', { name: 'Server (MCP)' })).toBeVisible()

  const example = await exampleText(page)
  expect(example).toContain('Bearer <YOUR_API_KEY>')
  expect(example).not.toContain('TWÓJ_KLUCZ_API')

  await expectNoLayoutDefects(page, 'karta „Serwer MCP" (SC-E6-2-06, EN)')
})

test.describe('SC-E6-2-06 porażka kopiowania (execCommand zwraca false)', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('komunikat błędu zamiast „Skopiowano", adres zaznaczony do ręcznej kopii (1440 px)', async ({
    page,
  }) => {
    await openApiKeys(page, '/user-setting/api', execCommandCopyFailure())
    const origin = await pageOrigin(page)
    const card = page.getByTestId('mcp-card')
    await expect(card).toBeVisible()

    await card.getByTestId('mcp-copy-http').click()

    // Czytelny błąd w miejscu potwierdzenia, bez fałszywego „Skopiowano”.
    await expect(card.getByTestId('mcp-error-http')).toBeVisible()
    await expect(card.getByTestId('mcp-error-http')).toContainText('Nie udało się skopiować')
    await expect(card.getByTestId('mcp-copy-http')).toContainText('Kopiuj')
    await expect(card.getByTestId('mcp-copy-http')).not.toContainText('Skopiowano')
    // Ręczne kopiowanie możliwe od razu: porażka zaznacza tekst adresu.
    expect(await page.evaluate(() => document.getSelection()?.toString())).toBe(`${origin}/mcp`)

    await expectNoLayoutDefects(page, 'karta „Serwer MCP" — porażka kopiowania (1440 px)')
  })
})

test.describe('SC-E6-2-06 porażka kopiowania 390 px', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('komunikat błędu czytelny na wąskim ekranie, bez wad układu', async ({ page }) => {
    await openApiKeys(page, '/user-setting/api', execCommandCopyFailure())
    const card = page.getByTestId('mcp-card')
    await expect(card).toBeVisible()

    await card.getByTestId('mcp-copy-example').click()

    await expect(card.getByTestId('mcp-error-example')).toBeVisible()
    await expect(card.getByTestId('mcp-copy-example')).not.toContainText('Skopiowano')

    await expectNoLayoutDefects(page, 'karta „Serwer MCP" — porażka kopiowania (390 px)')
  })
})
