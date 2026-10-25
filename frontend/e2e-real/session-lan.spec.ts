// U1 (K8 poprawka 2026-10-04b p. 2, WP E5-H6b T6): instalacja produkcyjna po HTTP pod adresem
// innym niż `localhost`/`127.0.0.1` utrzymuje sesję po F5 (cookie `wd_refresh` bez `Secure`).
// Uruchamiane przez `tools/dev/clean-install.sh` (WD_CI_SPEC=session-lan.spec.ts) na stosie
// produkcyjnym + nakładka fake-llm; adres stosu (host.docker.internal:<port>) wstrzykuje skrypt.
// Selektory jak użytkownik: role/etykiety/tekst (bez data-testid). Bez `--unsafely-treat-...`.
import { expect, test } from '@playwright/test'

const BASE_URL = process.env.WD_CI_BASE_URL ?? ''
const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''

// Adresy traktowane przez przeglądarkę jako „bezpieczne” (secure context) — dla nich cookie
// `Secure` działa nawet po HTTP, więc test nie sprawdzałby sesji po HTTP w LAN.
const LOCAL_ADDRESS = /(^|[/.:])localhost([/:]|$)|(^|[/.:])127\.0\.0\.1([/:]|$)/

test('session-lan: sesja po F5 przez HTTP w LAN (cookie wd_refresh bez Secure)', async ({
  page,
  context,
}) => {
  // (a) Test jest ważny wyłącznie na adresie innym niż localhost/127.0.0.1 — inaczej byłby
  //     fałszywie zielony (przeglądarka nie wymaga wtedy `Secure`).
  expect(
    LOCAL_ADDRESS.test(BASE_URL),
    `WD_CI_BASE_URL musi być adresem innym niż localhost/127.0.0.1 (jest: "${BASE_URL}")`,
  ).toBe(false)

  // (b) Logowanie formularzem kontem administracyjnym czystej instalacji.
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL)
  // `exact` — jak w clean-install.spec.ts: `getByLabel('Hasło')` trafia też w „Pokaż hasło”.
  await page.getByLabel('Hasło', { exact: true }).fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Zaloguj się' }).click()
  const nav = page.getByRole('navigation')
  await expect(nav.getByRole('link', { name: 'Bazy wiedzy' })).toBeVisible()

  // (c) Cookie sesji istnieje i NIE jest `Secure` (instalacja po HTTP) — to regresja T1 (C1).
  const refresh = (await context.cookies()).find((cookie) => cookie.name === 'wd_refresh')
  expect(refresh, 'cookie wd_refresh po logowaniu').toBeDefined()
  expect(refresh?.secure, 'wd_refresh.secure po HTTP').toBe(false)

  // (d) F5 — sesja utrzymana: nadal widać nawigację, a adres nie jest ekranem logowania.
  await page.reload()
  await expect(page).not.toHaveURL(/\/login/)
  await expect(
    page.getByRole('navigation').getByRole('link', { name: 'Bazy wiedzy' }),
  ).toBeVisible()

  // (e) Widok mobilny (390 px) — powłoka pokazuje nawigację w szufladzie (`AppNavbar` →
  //     hamburger „Otwórz menu”), więc otwieramy menu i sprawdzamy realnie widoczny link.
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page).not.toHaveURL(/\/login/)
  // Brak formularza logowania w DOM = pozostaliśmy na widoku zalogowanym (nie ma przekierowania).
  await expect(page.getByLabel('E-mail')).toHaveCount(0)
  await page.getByRole('button', { name: 'Otwórz menu' }).click()
  await expect(
    page.getByRole('navigation').getByRole('link', { name: 'Bazy wiedzy' }),
  ).toBeVisible()
})
