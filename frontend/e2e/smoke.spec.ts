// Scenariusz dymny harnessu (brief E3-2 T1): stos testowy odpowiada, a SPA startuje bez błędów
// konsoli. Strażnik błędów konsoli jest w fixture (e2e/fixtures.ts) — sprawdza się w teardownie.
import { expect, test } from './fixtures'

const API_URL = process.env.WD_E2E_API_URL ?? ''
// `request` (Node) nie zna mapowania `e2e.localhost` z przeglądarki, więc web sprawdzamy pod
// bezpośrednim adresem stosu (`WD_E2E_WEB_URL`); nawigacje `page.*` idą przez `use.baseURL`.
const WEB_URL = process.env.WD_E2E_WEB_URL ?? ''

test('stos testowy odpowiada i SPA startuje bez błędów konsoli', async ({ page, request }) => {
  // Bez `run.sh` zmienne nie są ustawione — jawny komunikat zamiast błędu DNS.
  expect(WEB_URL, 'brak WD_E2E_WEB_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')
  expect(API_URL, 'brak WD_E2E_API_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')

  const web = await request.get(`${WEB_URL}/healthz`)
  expect(web.status()).toBe(200)

  const api = await request.get(`${API_URL}/health/ready`)
  expect(api.status()).toBe(200)

  await page.goto('/')
  await expect(page.locator('#root')).toBeVisible()
})
