// Scenariusz S6-01 (brief E3-2 T5): wejście bez sesji, błąd logowania, poprawne logowanie,
// kolejność nawigacji głównej, odtworzenie sesji po F5 (cookie `wd_refresh`) i wylogowanie.
// Strażnik błędów konsoli/pageerror jest w fixture (e2e/fixtures.ts) — działa w teardownie.
import { ADMIN_EMAIL, ADMIN_PASSWORD, expect, test } from './fixtures'
import { expectNoSeriousA11y } from './helpers/axe'

// Etykiety nawigacji głównej (pl) w kolejności renderowania: lista główna (navItems.tsx
// `group: 'main'`), potem dolna (settings + admin). `agent`/`memory` wypadają bez flag,
// a `Administracja` wchodzi, bo admin z seedu K9 ma `is_superuser=1`; `Pomoc` wymaga DOCS_URL.
const NAV_LABELS = [
  'Start',
  'Bazy wiedzy',
  'Czat',
  'Wyszukiwanie',
  'Pliki',
  'Ustawienia',
  'Administracja',
]

test('S6-01: logowanie lokalne, nawigacja i wylogowanie', async ({ page }) => {
  // 1. Bez sesji `/` przekierowuje na `/login` z powrotem do bieżącego adresu.
  await page.goto('/')
  await expect(page).toHaveURL(/\/login\?redirect=/)
  await expect(page.getByTestId('login-email')).toBeVisible()

  // 2. Złe hasło: błąd z API (HTTP 200 + code 109) ląduje w alercie, adres zostaje na `/login`.
  await page.getByTestId('login-email').fill(ADMIN_EMAIL)
  await page.getByTestId('login-password').fill('niepoprawne-haslo')
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('login-error')).toBeVisible()
  await expect(page).toHaveURL(/\/login/)

  // 3. Poprawne dane → strona główna z banerem powitalnym (nickname admina z seedu = `admin`).
  await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
  await page.getByTestId('login-submit').click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByTestId('home-banner')).toHaveText(/Witaj w Wawelsky Dragon, admin/)

  // 4. Kolejność pozycji nawigacji głównej (`nav.main`) — bez klikania w pozycje.
  await expect(page.getByRole('navigation').getByRole('link')).toHaveText(NAV_LABELS)

  // Główny ekran scenariusza: strona główna po zalogowaniu (jasny motyw).
  await expectNoSeriousA11y(page, 'S6-01 strona główna')

  // 5. F5 odtwarza sesję z cookie `wd_refresh` (Secure) — nadal zalogowany, baner widoczny.
  await page.reload()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByTestId('home-banner')).toBeVisible()

  // 6. Wylogowanie z menu użytkownika → `/login`; F5 nie przywraca sesji.
  await page.getByRole('button', { name: 'Menu użytkownika' }).click()
  await page.getByRole('menuitem', { name: 'Wyloguj' }).click()
  await expect(page).toHaveURL(/\/login/)
  await page.reload()
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByTestId('login-email')).toBeVisible()
})
