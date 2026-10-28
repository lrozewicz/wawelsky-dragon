import { availableParallelism } from 'node:os'
import { defineConfig, configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Pod obciążeniem hosta (3 równoległe WP + stosy: load 50–90 na 32 wątkach) domyślne
// `availableParallelism() - 1` workerów zagładza sąsiednie procesy i ciężkie testy MUI
// przekraczają 15 s. Domyślnie bierzemy połowę rdzeni, ale nie więcej niż 12: pomiar pod
// obciążeniem (40 spinnerów + sąsiednie WP) dał przy 16 workerach testy 22,8 s, przy 12 — 10,9 s,
// przy 8 — 8,6 s; 12 to największa wartość, przy której cały suite mieści się w timeoutach.
// Wyrocznie mogą nadpisać liczbę przez `VITEST_MAX_WORKERS`.
// 2026-10-13 (właściciel): sufit 4 — kilka agentów naraz × 12 workerów jsdom wyczerpywało RAM hosta.
const MAX_WORKERS_LIMIT = 4
const defaultMaxWorkers = Math.max(
  2,
  Math.min(MAX_WORKERS_LIMIT, Math.floor(availableParallelism() / 2)),
)
const envMaxWorkers = Number.parseInt(process.env.VITEST_MAX_WORKERS ?? '', 10)
const maxWorkers =
  Number.isInteger(envMaxWorkers) && envMaxWorkers > 0 ? envMaxWorkers : defaultMaxWorkers

// Stała strefa czasowa: testy porównują sformatowane daty (np. `1.01.2025, 00:00:00` dla
// `2025-01-01T00:00:00Z`), więc w strefie lokalnej (Europe/Warsaw) padały, a w CI (UTC) przechodziły.
// Workery dziedziczą środowisko, dlatego ustawiamy ją już w konfiguracji.
process.env.TZ = 'UTC'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    maxWorkers,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Flaki pod obciążeniem CI/hosta (load ~20–30): domyślne 5 s na test i 10 s na hook to za mało
    // dla ciężkich plików (`ChatSettingsDrawer`, `ChatWorkspacePage`). Semantyka testów bez zmian.
    testTimeout: 15000,
    hookTimeout: 15000,
    // Katalogi `e2e/` i warianty `e2e-*` to scenariusze Playwrighta (`smoke.spec.ts`, krok
    // `clean-install` na stosie produkcyjnym, a1–a8 na stosie klienta) — poza vitestem; `serve.test.ts`
    // to test serwera statycznego uruchamiany osobno przez `bun test` (verify-fast).
    exclude: [...configDefaults.exclude, 'serve.test.ts', 'e2e/**', 'e2e-*/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'json-summary', 'cobertura'],
      include: [
        'src/lib/**',
        'src/api/**',
        'src/features/**',
        'src/hooks/**',
        'src/components/**',
        'src/i18n/**',
        'src/app/**',
      ],
      exclude: [
        'src/api/schema.gen.ts',
        'src/**/*.test.*',
        'src/test/**',
        'src/app/routerTypes.ts',
        'src/routeTree.gen.ts',
      ],
      thresholds: { lines: 80, functions: 80, statements: 80, branches: 75 },
    },
  },
})
