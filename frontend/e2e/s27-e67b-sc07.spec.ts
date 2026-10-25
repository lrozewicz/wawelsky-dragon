// Scenariusz SC-E67-07 (work/wp/E67-z/SCENARIOS.md, WP E67-z1b, brief T2): język, etykiety,
// nawigacja. Kroki: k1 (przycisk tworzenia wyszukiwarki PL/EN), k2 (jeden nagłówek „Pliki” w
// zakładce plików datasetu), k3 (etykieta „Motyw” na loginie, opcje nieucięte przy 390 px), k4
// (ikona ⓘ MCP w kolorze `secondary`, nie czerwona), k5 (nieznana ścieżka → „Nie znaleziono strony” w
// layoucie aplikacji; niezalogowany → logowanie), k6 (konto PL + przeglądarka EN → po wylogowaniu
// login nadal PL).
// Testy pisane PRZED implementacją (T4): niezrealizowane kroki są czerwone z właściwej
// przyczyny (inna etykieta / brak elementu), nie z błędu setupu.
// Wzorce: s20-mcp-card.spec.ts (karta MCP, sesja), s01-login.spec.ts (login, wylogowanie),
// helpers/session.ts (jedno logowanie na plik, kontekst bez sesji dla ekranu logowania).
import type { APIRequestContext, Locator } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, loginViaUi, seedCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { setProfileLanguage } from './helpers/models'
import { uiSession } from './helpers/session'

const NO_SESSION = { cookies: [], origins: [] }

let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

const session = uiSession('s27-e67b-sc07')
test.use({ storageState: session.statePath })
test.setTimeout(120_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context, request }) => {
  // Warianty EN/PL zmieniają język profilu — przywracamy PL dla kolejnych testów i plików.
  await setProfileLanguage(request, await adminToken(request), 'pl')
  await session.save(context)
})

test('SC-E67-07 krok 1: przycisk tworzenia wyszukiwarki — PL „Utwórz wyszukiwarkę”', async ({
  page,
}) => {
  await page.goto('/searches')
  await expect(
    page.getByRole('button', { name: 'Utwórz wyszukiwarkę', exact: true }).first(),
  ).toBeVisible()
  // Żadnych pozostałości angielskiego „Search” w polskich etykietach tworzenia.
  await expect(page.getByText(/Utwórz Search/i)).toHaveCount(0)
  await expectNoLayoutDefects(page, 'lista wyszukiwarek PL (SC-07 krok 1)')
})

test('SC-E67-07 krok 1: przycisk tworzenia wyszukiwarki — EN „Create search app”', async ({
  page,
  request,
}) => {
  await setProfileLanguage(request, await adminToken(request), 'en')
  await page.goto('/searches')
  await expect(
    page.getByRole('button', { name: 'Create search app', exact: true }).first(),
  ).toBeVisible()
  await expect(page.getByText(/Create Search\b(?! app)/)).toHaveCount(0)
  await expectNoLayoutDefects(page, 'lista wyszukiwarek EN (SC-07 krok 1)')
})

for (const viewport of [
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]) {
  test(`SC-E67-07 krok 2 (${viewport.width} px): zakładka plików datasetu ma jeden nagłówek „Pliki”`, async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const name = `E2E S27 pliki ${Date.now()}`
    // Dataset z plikiem: zakładka pokazuje tabelę plików (nie sam pusty stan).
    const { datasetId } = await seedCorpus(request, token, {
      datasetName: name,
      documentName: 'e2e-s27-pliki.txt',
      documentBody: 'Raport o stanie środowiska w Krakowie opisuje jakość powietrza i wód.',
    })
    try {
      await page.setViewportSize(viewport)
      await page.goto(`/dataset/files/${datasetId}`)
      await expect(page.getByRole('heading', { name })).toBeVisible()
      await expect(page.getByRole('tab', { name: 'Pliki' })).toBeVisible()
      // Pasek boczny ma własną pozycję „Pliki” (menedżer plików) — liczymy treść strony (`main`):
      // zakładka, ewentualny nagłówek i okruszek razem dają jedno wystąpienie „Pliki”.
      await expect(page.getByRole('main').getByText('Pliki', { exact: true })).toHaveCount(1)
      await expect(page.getByRole('heading', { name: 'Pliki', exact: true })).toHaveCount(0)
      await expectNoLayoutDefects(page, `zakładka plików datasetu (${viewport.width} px)`)
    } finally {
      await deleteDataset(request, token, datasetId)
    }
  })
}

for (const viewport of [
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]) {
  test(`SC-E67-07 krok 2 (${viewport.width} px): strona „Pliki” nie powtarza nagłówka „Pliki”`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await page.goto('/files')
    await expect(page.getByRole('heading', { name: 'Pliki', exact: true })).toBeVisible()
    // Treść strony (`main`) poza okruszkiem aplikacji w nagłówku (jedyna `nav` bez testid):
    // tytuł strony i korzeń okruszków plików (`files-breadcrumbs`) to dziś dwa „Pliki” pod sobą.
    const visibleLabels = await page.getByRole('main').evaluate((main) => {
      const isVisible = (el: Element): boolean => {
        const rect = el.getBoundingClientRect()
        return rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== 'hidden'
      }
      return [...main.querySelectorAll('*')]
        .filter(
          (el) =>
            el.children.length === 0 &&
            (el.textContent ?? '').trim() === 'Pliki' &&
            el.closest('nav:not([data-testid])') === null &&
            isVisible(el),
        )
        .map((el) => el.tagName.toLowerCase())
    })
    expect(visibleLabels, 'widoczne „Pliki” w treści strony').toHaveLength(1)
    await expectNoLayoutDefects(page, `strona Pliki (${viewport.width} px)`)
  })
}

test.describe('SC-E67-07 krok 3: etykieta selecta motywu na loginie', () => {
  test.use({ storageState: NO_SESSION })

  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 390, height: 844 },
  ]) {
    test(`SC-E67-07 krok 3 (${viewport.width} px): widoczna etykieta „Motyw”, opcje nieucięte`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport)
      await page.goto('/login')
      await expect(page.getByTestId('login-email')).toBeVisible()

      // Widoczny tekst etykiety (nie tylko aria-label) i select dostępny pod tą nazwą.
      await expect(page.getByText('Motyw', { exact: true })).toBeVisible()
      const select = page.getByRole('combobox', { name: /Motyw/ })
      await expect(select).toBeVisible()
      await select.click()
      const options = page.getByRole('option')
      await expect(options).toHaveCount(3)
      for (const label of ['Systemowy', 'Jasny', 'Ciemny']) {
        const option = page.getByRole('option', { name: label, exact: true })
        await expect(option).toBeInViewport({ ratio: 1 })
        const clipped = await option.evaluate((el) => el.scrollWidth > el.clientWidth + 1)
        expect(clipped, `opcja „${label}” ucięta`).toBe(false)
      }
      await expectNoLayoutDefects(page, `login z otwartym selectem motywu (${viewport.width} px)`)
    })
  }

  test.describe('EN', () => {
    test.use({ locale: 'en-US' })
    test('SC-E67-07 krok 3 (EN): etykieta „Theme”', async ({ page }) => {
      await page.goto('/login')
      await expect(page.getByTestId('login-email')).toBeVisible()
      await expect(page.getByText('Theme', { exact: true })).toBeVisible()
      await expect(page.getByRole('combobox', { name: /Theme/ })).toBeVisible()
    })
  })
})

/**
 * Kolor obliczony ikony ⓘ obok noty MCP oraz kolory tokenów `secondary`/`error` motywu (zmienne CSS
 * `--template-palette-*`, prefiks z `AppTheme` — `cssVarPrefix: 'template'`), sprowadzone do rgb
 * przez element-sondę, żeby porównanie nie zależało od zapisu (hex/rgb).
 */
async function mcpIconColors(
  icon: Locator,
): Promise<{ icon: string; secondary: string; error: string }> {
  return icon.evaluate((el) => {
    const resolve = (value: string): string => {
      const probe = document.createElement('span')
      probe.style.color = value
      document.body.appendChild(probe)
      const computed = getComputedStyle(probe).color
      probe.remove()
      return computed
    }
    return {
      icon: getComputedStyle(el).color,
      secondary: resolve('var(--template-palette-secondary-main)'),
      error: resolve('var(--template-palette-error-main)'),
    }
  })
}

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`SC-E67-07 krok 4 (${scheme})`, () => {
    test.use({ colorScheme: scheme })

    test(`SC-E67-07 krok 4 (${scheme}): ikona ⓘ w nocie MCP ma kolor secondary (steel), nie czerwony`, async ({
      page,
    }) => {
      await page.goto('/user-setting/api')
      const note = page.getByTestId('mcp-runbook-note')
      await expect(note).toBeVisible()
      const icon = note.locator('xpath=preceding-sibling::*[local-name()="svg"][1]')
      await expect(icon).toBeVisible()
      const colors = await mcpIconColors(icon)
      expect(colors.secondary, 'token secondary motywu rozwiązany do rgb').toMatch(/^rgb/)
      expect(colors.icon, 'kolor ikony = token secondary').toBe(colors.secondary)
      expect(colors.icon, 'kolor ikony ≠ token error').not.toBe(colors.error)
      await expectNoLayoutDefects(page, `karta MCP (${scheme}, SC-07 krok 4)`)
    })
  })
}

test.describe('SC-E67-07 krok 5: nieznana ścieżka', () => {
  for (const path of ['/chat', '/cokolwiek']) {
    test(`SC-E67-07 krok 5: zalogowany wpisuje ${path} → „Nie znaleziono strony” w layoucie`, async ({
      page,
    }) => {
      await page.goto(path)
      await expect(page.getByText('Nie znaleziono strony')).toBeVisible()
      // Strona w layoucie aplikacji (pasek nawigacji), nie goła odpowiedź „Not Found”.
      await expect(page.getByRole('navigation').first()).toBeVisible()
      await expect(page.getByText('Not Found', { exact: true })).toHaveCount(0)
      const link = page.getByRole('link', { name: 'Przejdź do Baz wiedzy' })
      await expect(link).toBeVisible()
      await expect(link).toHaveAttribute('href', /\/datasets$/)
      await expectNoLayoutDefects(page, `strona 404 ${path} (SC-07 krok 5)`)
      await link.click()
      await expect(page).toHaveURL(/\/datasets$/)
    })
  }

  test.describe('niezalogowany', () => {
    test.use({ storageState: NO_SESSION })
    test('SC-E67-07 krok 5: niezalogowany wpisuje /cokolwiek → ekran logowania', async ({
      page,
    }) => {
      await page.goto('/cokolwiek')
      await expect(page).toHaveURL(/\/login/)
      await expect(page.getByTestId('login-email')).toBeVisible()
      await expect(page.getByText('Nie znaleziono strony')).toHaveCount(0)
    })
  })
})

test.describe('SC-E67-07 krok 6: język konta ponad językiem przeglądarki', () => {
  // Przeglądarka angielska, konto polskie; własna sesja (wylogowanie unieważnia cookie pliku).
  test.use({ storageState: NO_SESSION, locale: 'en-US' })

  test('SC-E67-07 krok 6: konto PL + przeglądarka EN → po wylogowaniu login nadal PL', async ({
    page,
  }) => {
    await loginViaUi(page)
    await expect(page.getByTestId('home-banner')).toHaveText(/Witaj w Wawelsky Dragon/)

    // Zapytania startowe strony głównej kończą się przed wylogowaniem (inaczej spóźnione 401
    // zaśmieca konsolę i test padałby z powodu ścigania, nie języka).
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'Menu użytkownika' }).click()
    await page.getByRole('menuitem', { name: 'Wyloguj' }).click()
    await expect(page).toHaveURL(/\/login/)
    await expect(page.getByRole('heading', { name: 'Zaloguj się' })).toBeVisible()
    await expect(page.getByTestId('login-submit')).toHaveText('Zaloguj się')
    await expectNoLayoutDefects(page, 'login po wylogowaniu (SC-07 krok 6)')
  })
})
