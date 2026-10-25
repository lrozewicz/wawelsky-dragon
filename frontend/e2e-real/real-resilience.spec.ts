// Odporność workera na kontrolowaną awarię w trakcie parsowania (kontrakt WP E5-H5 §6, T3).
// Test A zabija proces potomny konwersji (największy VmRSS w kontenerze workera), test B — cały
// kontener workera; w obu przypadkach dokument GUS musi zakończyć czytelnie, a następny (sample.pdf)
// sparsować się do „Sukces” bez interwencji. kill.sh woła `execFileSync` (nigdy `pkill`).
// Selektory jak użytkownik: role/etykiety/tekst (bez data-testid).
import { execFileSync } from 'node:child_process'
import { readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

const ADMIN_EMAIL = process.env.WD_CI_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.WD_CI_ADMIN_PASSWORD ?? ''
// Nazwa projektu compose i korpus wstrzykuje clean-install.sh (kontrakt §1–§2).
const PROJECT = process.env.WD_CI_PROJECT ?? ''
const CORPUS = process.env.WD_REAL_CORPUS ?? ''

// Ścieżki bezwzględne liczone względem pliku spec (ESM, `__dirname` nie istnieje).
const SAMPLE_PDF = fileURLToPath(new URL('../e2e/fixtures/sample.pdf', import.meta.url))
const KILL_SH = fileURLToPath(new URL('../../tools/dev/real/kill.sh', import.meta.url))
const COLLECT_SH = fileURLToPath(new URL('../../tools/dev/real/collect.sh', import.meta.url))

const GUS_NAME = 'gus_rocznik_statystyczny_rp_2024.pdf'
const DATASET_A = 'Resilience child'
const DATASET_B = 'Resilience worker'

// Teksty stanów z locale pl (datasets.files.status.*): „Sukces”/„Błąd”.
const DONE = /Sukces/
const FAILED = /Błąd/

// Czytelny powód błędu (kontrakt §6): wzmianka o pamięci, awarii, przerwaniu lub ponowieniu.
// Wzorzec zmierzony na stosie WP E5-H5 T3 — przy zmianie komunikatów UI dopasuj tutaj.
const READABLE = /pamię|awari|przerwa|ponown|restart|zabity|memory|crash|interrupt|again|retry/i
// Wewnętrzne szczegóły (stack trace, pula procesów, błąd serwera) nie mogą być przyczyną dla użytkownika.
const UNREADABLE = /BrokenProcessPool|Traceback|Internal|File "\//i

/** Rekurencyjnie znajduje plik o danej nazwie w korpusie; brak → wyjątek. */
function findCorpusFile(name: string): string {
  if (CORPUS === '') throw new Error('WD_REAL_CORPUS nieustawione')
  const stack = [CORPUS]
  while (stack.length > 0) {
    const dir = stack.pop()
    if (dir === undefined) break
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) stack.push(full)
      else if (entry.name === name) return full
    }
  }
  throw new Error(`brak pliku ${name} w ${CORPUS}`)
}

/** Kontrolowana awaria stosu: `child` (potomek konwersji) albo `worker` (kontener). */
function kill(target: 'child' | 'worker'): void {
  try {
    execFileSync(KILL_SH, [target, PROJECT], { stdio: 'pipe', timeout: 240_000 })
  } catch (error) {
    const stderr = (error as { stderr?: Buffer }).stderr?.toString().trim() ?? ''
    throw new Error(`kill.sh ${target} ${PROJECT} nie powiódł się: ${stderr}`, { cause: error })
  }
}

async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(ADMIN_EMAIL)
  // `exact` — inaczej `getByLabel('Hasło')` trafia też w przycisk „Pokaż hasło”.
  await page.getByLabel('Hasło', { exact: true }).fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Zaloguj się' }).click()
  const nav = page.getByRole('navigation')
  await expect(nav.getByRole('link', { name: 'Bazy wiedzy' })).toBeVisible()
  await nav.getByRole('link', { name: 'Bazy wiedzy' }).click()
  await expect(page).toHaveURL(/\/datasets$/)
}

/** Tworzy dataset domyślnym modelem instancji (pole embeddingu wypełnia się samo). */
async function createDataset(page: Page, name: string): Promise<void> {
  await page.getByRole('button', { name: 'Utwórz dataset' }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Nazwa').fill(name)
  await dialog.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
}

/** Upload przez okno wyboru z domyślnym „Parsuj po przesłaniu” (wzorzec clean-install.spec.ts). */
async function uploadFile(page: Page, file: string): Promise<void> {
  await page.getByRole('button', { name: 'Prześlij plik' }).click()
  const uploadDialog = page.getByRole('dialog')
  await expect(uploadDialog.getByRole('heading', { name: 'Prześlij pliki' })).toBeVisible()
  await expect(uploadDialog.getByRole('switch', { name: 'Parsuj po przesłaniu' })).toBeChecked()
  const chooser = page.waitForEvent('filechooser')
  await uploadDialog.getByRole('button', { name: 'Wybierz pliki' }).click()
  await (await chooser).setFiles(file)
  await uploadDialog.getByRole('button', { name: 'Prześlij' }).click()
  await expect(uploadDialog.getByText('Przesłano', { exact: true })).toBeVisible({
    timeout: 180_000,
  })
  await uploadDialog.getByRole('button', { name: 'Gotowe' }).click()
}

/**
 * Czeka (przez `expect.poll`, bez `waitForTimeout`) na końcowy stan wiersza: „Sukces” albo „Błąd”.
 * Toleruje chwilowe błędy odczytu/sprawdzenia listy (restart workera) — wtedy próbuje dalej.
 */
async function waitForFinalState(row: Locator, timeoutMs: number): Promise<string> {
  let text = ''
  await expect
    .poll(
      async () => {
        try {
          text = await row.innerText()
        } catch {
          return 'pending'
        }
        if (DONE.test(text)) return 'done'
        if (FAILED.test(text)) return 'failed'
        return 'pending'
      },
      { timeout: timeoutMs, intervals: [5_000] },
    )
    .not.toBe('pending')
  return text
}

// Limit oczekiwania na stan końcowy GUS po killu workera (WP E5-H6c, DEC-260). Wyprowadzenie:
// restart kontenera przez Dockera i kill.sh ≤ 2 min; `release_own_host` przy starcie zwalnia osierocone
// zadanie od razu (bez czekania na reapera: task_stale_s=120 s + tick 60 s + backoff); potem pełne ponowne
// parsowanie GUS — zmierzone 8–10 min pod obciążeniem hosta (load ~25) → 2 + 10 = 12 min, margines
// +25% = 15 min. Zmienna WD_RESILIENCE_FINAL_MS służy tylko do wymuszenia porażki w celu sprawdzenia artefaktów.
const FINAL_STATE_TIMEOUT_MS = Number(process.env.WD_RESILIENCE_FINAL_MS ?? '900000')

/**
 * Po killu domyka wątek GUS: „Sukces” albo błąd z czytelną przyczyną (kontrakt §6). Stan końcowy
 * (i treść błędu) logujemy — trafia do raportu TL. Dokument zawieszony w „Parsowaniu” = czerwień.
 */
async function finishGus(page: Page, row: Locator, label: string): Promise<void> {
  const text = await waitForFinalState(row, FINAL_STATE_TIMEOUT_MS)
  if (!FAILED.test(text)) {
    console.log(`[resilience] ${label}: GUS zakończony stanem: Sukces`)
    return
  }
  await row.getByText('Błąd', { exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  const log = (await dialog.innerText()).replace(/\s+/g, ' ').trim()
  console.log(`[resilience] ${label}: GUS zakończony stanem: Błąd — ${log.slice(0, 500)}`)
  expect(log, `${label}: czytelny powód błędu GUS`).toMatch(READABLE)
  expect(log, `${label}: powód bez wewnętrznych szczegółów`).not.toMatch(UNREADABLE)
  await dialog.getByRole('button', { name: 'Zamknij' }).click()
}

/** Po awarii kolejny dokument musi sparsować się sam, bez ręcznej interwencji. */
async function uploadAndExpectSuccess(page: Page, file: string, name: string): Promise<void> {
  await uploadFile(page, file)
  const row = page.getByRole('row').filter({ hasText: name })
  await expect(row).toContainText(DONE, { timeout: 240_000 })
}

test.describe.configure({ mode: 'serial' })

// Po porażce testu zostaw w katalogu raportu artefakty diagnostyczne stosu (kontrakt E5-H6c §K3).
// Błąd collect.sh tylko logujemy — nie maskujemy pierwotnej porażki testu.
test.afterEach(async () => {
  // Playwright odrzuca pierwszy argument bez destrukturyzacji; `test.info()` zastępuje drugi parametr.
  const testInfo = test.info()
  if (testInfo.status !== testInfo.expectedStatus) {
    const dir = join(
      process.env.WD_REAL_OUT ?? 'test-results-real/report',
      'artifacts-' + testInfo.title.slice(0, 1),
    )
    try {
      execFileSync(COLLECT_SH, [PROJECT, dir], { stdio: 'pipe', timeout: 120_000 })
    } catch (error) {
      console.log(`[resilience] collect.sh nie powiódł się: ${(error as Error).message}`)
    }
  }
})

test('A: zabicie potomka konwersji w trakcie parsowania GUS', async ({ page }) => {
  test.setTimeout(1_200_000)
  const gusPdf = findCorpusFile(GUS_NAME)

  await loginAsAdmin(page)
  await createDataset(page, DATASET_A)
  await uploadFile(page, gusPdf)

  // Wiersz GUS w stanie „Parsowanie” (progressbar „Postęp parsowania” z locale).
  const row = page.getByRole('row').filter({ hasText: GUS_NAME })
  await expect(row.getByRole('progressbar', { name: 'Postęp parsowania' })).toBeVisible({
    timeout: 300_000,
  })

  kill('child')
  await finishGus(page, row, 'A')

  await uploadAndExpectSuccess(page, SAMPLE_PDF, 'sample.pdf')
})

test('B: zabicie kontenera workera w trakcie parsowania GUS', async ({ page }) => {
  test.setTimeout(1_200_000)
  const gusPdf = findCorpusFile(GUS_NAME)

  await loginAsAdmin(page)
  await createDataset(page, DATASET_B)
  await uploadFile(page, gusPdf)

  const row = page.getByRole('row').filter({ hasText: GUS_NAME })
  await expect(row.getByRole('progressbar', { name: 'Postęp parsowania' })).toBeVisible({
    timeout: 300_000,
  })

  kill('worker')
  // Po restarcie workera lista może chwilowo nie odpowiadać — `finishGus` odpytuje przez expect.poll.
  await finishGus(page, row, 'B')

  await uploadAndExpectSuccess(page, SAMPLE_PDF, 'sample.pdf')
})
