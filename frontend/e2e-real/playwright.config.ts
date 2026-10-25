import { defineConfig, devices } from '@playwright/test'

// Konfiguracja Playwright kroku "clean-install" (K1 poprawka 2026-10-04 p. 1, WP E5-H1 T3).
// Uruchamia ją wyłącznie tools/dev/clean-install.sh — adres stosu i konto administracyjne
// wstrzykuje skrypt przez WD_CI_* (stos produkcyjny + nakładka fake-llm, bez seedu K9).
// Osobna od frontend/playwright.config.ts (stos testowy) i bez zmian w package.json.
const BASE_URL = process.env.WD_CI_BASE_URL

export default defineConfig({
  testDir: '.',
  // Spec wskazuje clean-install.sh przez WD_CI_SPEC (kontrakt WP E5-H5 §1); bez zmiennej — krok
  // "clean-install" verify-full działa jak dotąd.
  testMatch: process.env.WD_CI_SPEC ?? 'clean-install.spec.ts',
  outputDir: '../test-results-real',
  // Domyślne budżety (DEC-375): per test 10 min; asercje `expect` bez jawnego timeoutu — 60 s.
  // Najdłuższe realne kroki (ingestia rocznika GUS, parsowanie OCR) mają własne `test.setTimeout`
  // i jawne limity per krok w specach.
  timeout: 600_000,
  expect: { timeout: 60_000 },
  retries: 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: BASE_URL,
    locale: 'pl-PL',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
