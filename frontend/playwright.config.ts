import { defineConfig, devices } from '@playwright/test'

// Konfiguracja Playwright (kontrakt WP E3-2, brief T1). Adres stosu testowego wstrzykuje
// `e2e/run.sh` (WD_E2E_BASE_URL, WD_E2E_API_URL) — uruchamiany poza nim musi je ustawić sam.
const BASE_URL = process.env.WD_E2E_BASE_URL
const POLISH_UI = {
  cookies: [],
  origins: BASE_URL
    ? [{ origin: BASE_URL, localStorage: [{ name: 'wd.language', value: 'pl' }] }]
    : [],
}

export default defineConfig({
  testDir: './e2e',
  outputDir: 'test-results',
  globalSetup: './e2e/global-setup.ts',
  // Kwarantanna flaków (analiza 2026-10-09: ~12 z 31 czerwonych verify-full to flaki/środowisko): jedno ponowienie;
  // test zielony dopiero za drugim razem kończy bieg zielono, ale run.sh wypisuje go jako FLAKY do raportu TL.
  retries: Number(process.env.WD_E2E_RETRIES ?? 1),
  // Zrzuty wzorcowe (e2e/visual.spec.ts, analiza 2026-10-09): brak wzorca = adnotacja w teście (nie porażka);
  // wzorce tworzy i zmienia się świadomie: `bun run e2e -- e2e/visual.spec.ts --update-snapshots` + obejrzenie + commit.
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.01,
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    },
  },
  workers: 1,
  reporter: [['list'], ['json', { outputFile: 'test-results/e2e-results.json' }]],
  use: {
    baseURL: BASE_URL,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      // Aplikacja domyślnie startuje po angielsku, a po zalogowaniu przyjmuje język profilu.
      // Scenariusze asertują polskie etykiety także przed zalogowaniem, stąd zapisany wybór.
      use: { ...devices['Desktop Chrome'], locale: 'pl-PL', storageState: POLISH_UI },
    },
  ],
})
