// Wzorce wizualne dialogów eksportu/importu i paska zadań (WP E7-2 T7, ten cel co visual.spec.ts:
// wady wizualne — nakładanie, ucięcia, okna poza ekranem — znajdował dopiero właściciel). Każdy
// wzorzec × wariant (jasny 1280, ciemny 1280, jasny 390 — jak w visual.spec.ts) robi dwie rzeczy:
//   1. `expectNoLayoutDefects` — deterministyczna kontrola układu (helpers/layout.ts),
//   2. `toHaveScreenshot` — porównanie ze zrzutem wzorcowym w `visual-kb-transfer.spec.ts-snapshots/`.
// Stan dialogów i paska wymuszamy przez `page.route` na trasy K19 `/api/wd/v1/...` (odpowiedzi
// wg docs/contracts/K19-eksport-import.md §3) i zasiew `localStorage` `wd.kbTasks.v1:<userId>` —
// wzorce NIE zależą od backendu K19. Dane celowo stabilne: stałe liczby, daty i nazwy ASCII.
// Aktualizacja wzorców jak w visual.spec.ts: `bun run e2e -- e2e/visual-kb-transfer.spec.ts
// --update-snapshots` + obejrzenie nowych plików (Read) i wpis w raporcie TL.
import { existsSync } from 'node:fs'

import type { Locator, Page, Route } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, createDataset } from './helpers'
import { expectNoLayoutDefects } from './helpers/layout'

const API_URL = process.env.WD_E2E_API_URL ?? ''

const DATASET_NAME = 'Roczniki statystyczne GUS 2019-2024'
const MODEL = 'BAAI/bge-m3'
const MODEL_ALT = 'intfloat/multilingual-e5-large'
const PACKAGE_NAME = 'roczniki-gus.wdkb.zip'
// Stałe daty (zrzuty stabilne między biegami): moment utworzenia zadań i termin linku pobrania.
const CREATED_MS = Date.UTC(2026, 9, 12, 9, 30)
const EXPIRES_MS = Date.UTC(2027, 0, 15, 12, 0)
const CREATED_ISO = '2026-10-12T09:30:00Z'
// Paczka 1,5 MB < `chunk_size` (8 MiB z K19 §3) — jedna porcja `PUT`.
const PACKAGE_BYTES = 1_572_864

// Kształty z K19 §3 (podzbiór pól używanych przez UI) — kontrakt `frontend/src/features/kb-transfer/types.ts`.
type ExportResult = {
  download_url: string
  expires_at: number
  size_bytes: number
  file_name: string
}
type ImportResult = {
  dataset_id: string
  dataset_name: string
  documents: number
  chunks: number
  reembedded: boolean
}
type WdTask = {
  task_id: string
  kind: 'export' | 'import'
  dataset_id: string | null
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  stage: 'files' | 'documents' | 'chunks' | 'vectors' | 'embedding' | 'finalize' | null
  done: number
  total: number
  progress: number
  message: string
  error: { code: string; message: string } | null
  created_at: number
  finished_at: number | null
  result: ExportResult | ImportResult | null
}
type StoredKbTask = {
  task_id: string
  kind: 'export' | 'import'
  label: string
  dataset_id: string | null
  added_at: number
  last: WdTask | null
}
type ImportSummary = {
  name: string
  description: string | null
  documents: number
  chunks: number
  schema_version: number
  wd_version: string
  created_at: string
  embedding: { model_name: string; dimension: number; included: boolean }
  target: {
    compatible: boolean
    default_model: string | null
    models: { name: string; dimension: number }[]
  }
  suggested_name: string
  name_taken: boolean
  estimated_reembed_tokens: number
}
type DatasetImport = {
  import_id: string
  file_name: string
  size_bytes: number
  received_bytes: number
  chunk_size: number
  state: 'uploading' | 'ready' | 'invalid' | 'started' | 'expired'
  errors: { code: string; message: string }[]
  summary: ImportSummary | null
  task_id: string | null
  expires_at: number
}
type ExportPreview = {
  dataset_id: string
  name: string
  documents: number
  chunks: number
  estimated_bytes: number
  estimated_bytes_with_vectors: number
  embedding: { model_name: string; dimension: number }
  max_bytes: number
}

type Variant = { name: string; viewport: { width: number; height: number }; dark: boolean }

const VARIANTS: Variant[] = [
  { name: 'light-1280', viewport: { width: 1280, height: 800 }, dark: false },
  { name: 'dark-1280', viewport: { width: 1280, height: 800 }, dark: true },
  { name: 'light-390', viewport: { width: 390, height: 844 }, dark: false },
]

const PREVIEW: ExportPreview = {
  dataset_id: 'ds-visual-1',
  name: DATASET_NAME,
  documents: 12,
  chunks: 348,
  estimated_bytes: 25_165_824,
  estimated_bytes_with_vectors: 104_857_600,
  embedding: { model_name: MODEL, dimension: 1024 },
  max_bytes: 2_147_483_648,
}

const RUNNING_EXPORT: WdTask = {
  task_id: 'task-visual-running',
  kind: 'export',
  dataset_id: 'ds-visual-1',
  status: 'running',
  stage: 'chunks',
  done: 120,
  total: 348,
  progress: 0.345,
  message: 'Chunki 120/348',
  error: null,
  created_at: CREATED_MS,
  finished_at: null,
  result: null,
}

const DONE_EXPORT: WdTask = {
  task_id: 'task-visual-export',
  kind: 'export',
  dataset_id: 'ds-visual-1',
  status: 'done',
  stage: null,
  done: 348,
  total: 348,
  progress: 1,
  message: 'Gotowe',
  error: null,
  created_at: CREATED_MS,
  finished_at: CREATED_MS,
  result: {
    download_url:
      '/api/wd/v1/exports/task-visual-export/download?exp=1799991600&sig=0f1e2d3c4b5a69788796a5b4c3d2e1f0',
    expires_at: EXPIRES_MS,
    size_bytes: 104_857_600,
    file_name: PACKAGE_NAME,
  },
}

const DONE_IMPORT: WdTask = {
  task_id: 'task-visual-import',
  kind: 'import',
  dataset_id: 'ds-visual-imported',
  status: 'done',
  stage: null,
  done: 348,
  total: 348,
  progress: 1,
  message: 'Gotowe',
  error: null,
  created_at: CREATED_MS,
  finished_at: CREATED_MS,
  result: {
    dataset_id: 'ds-visual-imported',
    dataset_name: 'Roczniki GUS',
    documents: 12,
    chunks: 348,
    reembedded: false,
  },
}

const FAILED_EXPORT: WdTask = {
  task_id: 'task-visual-failed',
  kind: 'export',
  dataset_id: 'ds-visual-1',
  status: 'failed',
  stage: null,
  done: 121,
  total: 348,
  progress: 0.348,
  message: 'Błąd',
  error: {
    code: 'checksum_mismatch',
    message: 'Suma kontrolna pliku vectors.npy nie zgadza się z rekordem manifestu.',
  },
  created_at: CREATED_MS,
  finished_at: CREATED_MS,
  result: null,
}

// Krok 2 zgodny: paczka z wektorami, model paczki dostępny u aktora — „Zgodny z paczką”.
const SUMMARY_OK: ImportSummary = {
  name: 'Roczniki GUS',
  description: null,
  documents: 12,
  chunks: 348,
  schema_version: 1,
  wd_version: '1.4.0',
  created_at: CREATED_ISO,
  embedding: { model_name: MODEL, dimension: 1024, included: true },
  target: {
    compatible: true,
    default_model: MODEL,
    models: [
      { name: MODEL, dimension: 1024 },
      { name: MODEL_ALT, dimension: 1024 },
    ],
  },
  suggested_name: 'Roczniki GUS',
  name_taken: false,
  estimated_reembed_tokens: 0,
}

// Krok 2 niezgodny model: model paczki niedostępny u aktora — ostrzeżenie o przeliczeniu chunków.
const SUMMARY_REEMBED: ImportSummary = {
  ...SUMMARY_OK,
  target: {
    compatible: false,
    default_model: MODEL_ALT,
    models: [{ name: MODEL_ALT, dimension: 1024 }],
  },
  estimated_reembed_tokens: 1_920_000,
}

const PACKAGE_ERRORS: DatasetImport['errors'] = [
  {
    code: 'schema_too_new',
    message: 'Paczka z nowszej wersji Wawelsky Dragon (schemat 9) — zaktualizuj instalację.',
  },
  {
    code: 'checksum_mismatch',
    message: 'Suma kontrolna pliku chunks.npy nie zgadza się z rekordem.',
  },
]

let userId = ''
/** Prawdziwy access token z seedu — trasy loginu w testach go wstrzykują (limiter 10/min). */
let sessionToken = ''

test.beforeAll(async ({ request }) => {
  await resetDb(request)
  const token = await apiLogin(request)
  sessionToken = token
  const profile = await request.get(`${API_URL}/api/v1/users/me`, {
    headers: { authorization: `Bearer ${token}` },
  })
  expect(profile.status(), 'GET /api/v1/users/me').toBe(200)
  const me = (await profile.json()) as { data: { id: string } }
  userId = me.data.id
  await createDataset(request, token, DATASET_NAME)
})

// Stan wyjściowy dla kolejnych specyfikacji: seed K9 jak po global-setup.
test.afterAll(async ({ request }) => {
  await resetDb(request)
})

/** Ekran gotowy: brak wskaźników ładowania, czcionki wczytane. */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle')
  await expect(page.locator('.MuiCircularProgress-root, .MuiSkeleton-root')).toHaveCount(0, {
    timeout: 15_000,
  })
  await page.evaluate(() => document.fonts.ready)
}

async function check(page: Page, pattern: string, variant: Variant): Promise<void> {
  await settle(page)
  await expectNoLayoutDefects(page, `${pattern} (${variant.name})`, { soft: true })
  const name = `${pattern}-${variant.name}.png`
  const updating = test.info().config.updateSnapshots === 'all'
  // Brak wzorca nie oblewa biegu (wzorce tworzy się świadomie: `--update-snapshots` w kontenerze agentów,
  // potem obejrzenie Read i commit) — zrzut idzie jako załącznik z adnotacją `visual-baseline-missing`.
  if (!updating && !existsSync(test.info().snapshotPath(name))) {
    test.info().annotations.push({ type: 'visual-baseline-missing', description: name })
    await test.info().attach(name, { body: await page.screenshot(), contentType: 'image/png' })
    return
  }
  await expect(page).toHaveScreenshot(name)
}

/** Sukces trasy wd K19: koperta `{data}` (K3 §3 p. 4). */
async function fulfillData(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, json: { data: body } })
}

/** Mock trasy 1 (K19 §3): podgląd eksportu dla dialogu. */
async function mockExportPreview(page: Page): Promise<void> {
  await page.route('**/api/wd/v1/datasets/*/export/preview', (route) => fulfillData(route, PREVIEW))
}

/** Mock tras 6 i 7 (K19 §3): sesja importu; `final` = odpowiedź kończącej porcji (`PUT`). */
async function mockImportUpload(page: Page, final: DatasetImport): Promise<void> {
  await page.route('**/api/wd/v1/dataset-imports/*/content', (route) => fulfillData(route, final))
  await page.route('**/api/wd/v1/dataset-imports', (route) =>
    fulfillData(route, importSession('uploading', null, []), 201),
  )
}

/** Odpowiedź tras 6–8: sesja importu o stałym identyfikatorze i rozmiarze paczki. */
function importSession(
  state: DatasetImport['state'],
  summary: ImportSummary | null,
  errors: DatasetImport['errors'],
): DatasetImport {
  return {
    import_id: 'imp-visual-1',
    file_name: PACKAGE_NAME,
    size_bytes: PACKAGE_BYTES,
    received_bytes: state === 'uploading' ? 0 : PACKAGE_BYTES,
    chunk_size: 8_388_608,
    state,
    errors,
    summary,
    task_id: null,
    expires_at: EXPIRES_MS,
  }
}

/** Zasiew wierszy paska zadań aktora przed startem aplikacji (init script — jak s17 krok 8 F5). */
async function seedRows(page: Page, userIdKey: string, rows: StoredKbTask[]): Promise<void> {
  await page.addInitScript(
    ({ key, value }) => {
      localStorage.setItem(key, value)
    },
    { key: userIdKey, value: JSON.stringify(rows) },
  )
}

/** Wiersz magazynu dla zadania z wzorca (added_at świeże — filtr TTL 24 h nie wycina). */
function storedRow(task: WdTask, kind: 'export' | 'import', label: string): StoredKbTask {
  return {
    task_id: task.task_id,
    kind,
    label,
    dataset_id: task.dataset_id,
    added_at: Date.now() - 60_000,
    last: task,
  }
}

/**
 * Sesja dla wzorca: trasa `POST /auth/refresh` odpowiada prawdziwym tokenem z `beforeAll`,
 * więc aplikacja wstaje już zalogowana (boot: `ensureSession` → `refresh` → `GET /users/me`
 * → home) i pełny reload (`goto('/datasets')`) też dostaje sesję. Prawdziwa droga (formularz
 * + `POST /auth/login`) to 27 logowań na bieg, a limiter backendu (10/min na IP+e-mail,
 * CONTRACT E5-2a §4) odrzuca nadwyżkę 429 „Too many login attempts" — ekran logowania
 * zostawał i `home-banner` nie występował. Backend widzi jedno logowanie na bieg (TTL tokenu
 * 15 min > czas biegu i retry); formularz logowania we wzorcach nie występuje.
 */
async function login(page: Page): Promise<void> {
  // Koperta RAGFlow (`{code, data}`, envelope.ts) — inne kształty niż trasy wd (`fulfillData`).
  await page.route('**/api/v1/auth/refresh', (route) =>
    route.fulfill({
      status: 200,
      json: { code: 0, data: { access_token: sessionToken, expires_in: 900 } },
    }),
  )
  await page.goto('/')
  await expect(page.getByTestId('home-banner')).toBeVisible({ timeout: 20_000 })
}

/** Lista baz po zalogowaniu — karta seeded bazy widoczna (punkty wyjścia wszystkich wzorców). */
async function openDatasets(page: Page): Promise<void> {
  await login(page)
  await page.goto('/datasets')
  await expect(page.getByTestId('dataset-card').filter({ hasText: DATASET_NAME })).toBeVisible()
}

/** Dialog eksportu z menu ⋮ karty bazy (CONTRACT WP E7-2 §7). */
async function openExportDialog(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: `Menu bazy wiedzy ${DATASET_NAME}` }).click()
  await page.getByRole('menuitem', { name: 'Eksportuj' }).click()
  const dialog = page.getByRole('dialog', { name: `Eksportuj „${DATASET_NAME}”` })
  await expect(dialog).toBeVisible()
  return dialog
}

/** Dialog importu z przycisku nagłówka (krok 1: strefa upuszczania). */
async function openImportDialog(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: 'Importuj', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
  await expect(dialog.getByTestId('kb-import-dropzone')).toBeVisible()
  return dialog
}

/** Lista baz z zasianym jednym wierszem paska; zadania niekońcowe dostają mock odpytania (trasa 3). */
async function openTaskBar(page: Page, task: WdTask, kind: 'export' | 'import'): Promise<void> {
  if (task.status === 'running' || task.status === 'queued') {
    await page.route(`**/api/wd/v1/tasks/${task.task_id}`, (route) => fulfillData(route, task))
  }
  await seedRows(page, `wd.kbTasks.v1:${userId}`, [storedRow(task, kind, DATASET_NAME)])
  await openDatasets(page)
  await expect(page.getByTestId('kb-task-bar')).toBeVisible()
  await expect(page.getByTestId('kb-task-row')).toHaveCount(1)
}

for (const variant of VARIANTS) {
  test.describe(`wygląd kb-transfer ${variant.name}`, () => {
    test.use({ viewport: variant.viewport, colorScheme: variant.dark ? 'dark' : 'light' })

    test(`dialog eksportu — ${variant.name}`, async ({ page }) => {
      await mockExportPreview(page)
      await openDatasets(page)
      const dialog = await openExportDialog(page)
      await expect(dialog.getByTestId('kb-export-summary')).toBeVisible()
      await check(page, 'export-dialog', variant)
    })

    test(`dialog importu krok 1 — ${variant.name}`, async ({ page }) => {
      await openDatasets(page)
      await openImportDialog(page)
      await check(page, 'import-dialog-pick', variant)
    })

    test(`dialog importu krok 2 zgodny — ${variant.name}`, async ({ page }) => {
      await mockImportUpload(page, importSession('ready', SUMMARY_OK, []))
      await openDatasets(page)
      const dialog = await openImportDialog(page)
      await dialog.locator('input[type="file"]').setInputFiles({
        name: PACKAGE_NAME,
        mimeType: 'application/zip',
        buffer: Buffer.alloc(PACKAGE_BYTES, 0x57),
      })
      await expect(dialog.getByTestId('kb-import-summary')).toBeVisible()
      await expect(dialog.getByTestId('kb-import-compatible')).toBeVisible()
      await check(page, 'import-dialog-summary', variant)
    })

    test(`dialog importu krok 2 niezgodny model — ${variant.name}`, async ({ page }) => {
      await mockImportUpload(page, importSession('ready', SUMMARY_REEMBED, []))
      await openDatasets(page)
      const dialog = await openImportDialog(page)
      await dialog.locator('input[type="file"]').setInputFiles({
        name: PACKAGE_NAME,
        mimeType: 'application/zip',
        buffer: Buffer.alloc(PACKAGE_BYTES, 0x57),
      })
      await expect(dialog.getByTestId('kb-import-summary')).toBeVisible()
      await expect(dialog.getByTestId('kb-import-reembed')).toBeVisible()
      await check(page, 'import-dialog-reembed', variant)
    })

    test(`dialog importu lista błędów — ${variant.name}`, async ({ page }) => {
      await mockImportUpload(page, importSession('invalid', null, PACKAGE_ERRORS))
      await openDatasets(page)
      const dialog = await openImportDialog(page)
      await dialog.locator('input[type="file"]').setInputFiles({
        name: PACKAGE_NAME,
        mimeType: 'application/zip',
        buffer: Buffer.alloc(PACKAGE_BYTES, 0x57),
      })
      await expect(dialog.getByTestId('kb-import-invalid')).toBeVisible()
      await check(page, 'import-dialog-invalid', variant)
    })

    test(`pasek zadań w toku — ${variant.name}`, async ({ page }) => {
      await openTaskBar(page, RUNNING_EXPORT, 'export')
      await check(page, 'task-bar-running', variant)
    })

    test(`pasek zadań gotowy eksport — ${variant.name}`, async ({ page }) => {
      await openTaskBar(page, DONE_EXPORT, 'export')
      await check(page, 'task-bar-export-done', variant)
    })

    test(`pasek zadań gotowy import — ${variant.name}`, async ({ page }) => {
      await openTaskBar(page, DONE_IMPORT, 'import')
      await check(page, 'task-bar-import-done', variant)
    })

    test(`pasek zadań błąd — ${variant.name}`, async ({ page }) => {
      await openTaskBar(page, FAILED_EXPORT, 'export')
      await check(page, 'task-bar-failed', variant)
    })
  })
}
