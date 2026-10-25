// Scenariusze E7-2: eksport bazy wiedzy w UI (SCENARIOS.md SC-E7-2-01 + warianty i SC-E7-2-05;
// spec UX 08-frontend §7.15(a)(b); kontrakt K19 §3, nazwy i data-testid: CONTRACT E7-2 §7).
// Dane: korpus poza repo (rocznik GUS + wzór raportu NCBR) przez `helpers/kbTransfer.ts`;
// zasiew biegnie RAZ na plik (wzór: s07-chat-citations), bo parsowanie GUS trwa ~10 min.
// Logowanie RAZ na plik przez sesję `uiSession` (T10, wzór: s17-model-edit): limiter logowań
// 10/min (WD_RATE_LIMIT_LOGIN) liczy KAŻDĄ próbę, a testów w pliku jest kilkanaście — świeże
// logowanie w każdym z nich tripiło falę 429 w pierwszym biegu na prawdziwym backendzie.
import { readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createDataset, loginViaUi } from './helpers'
import { deleteUserByEmail, loginViaUiAs, watchConsoleErrors } from './helpers/admin'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { uiSession } from './helpers/session'
import {
  CHUNK_WORD_RE,
  authHeaders,
  clearKbTaskRows,
  copiedText,
  createDatasetWithPermission,
  createUserByApi,
  deleteDatasetsNamed,
  escapeRegExp,
  execCommandCopySpy,
  loginToken,
  ragOk,
  seedExportDataset,
  waitTask,
} from './helpers/kbTransfer'

const session = uiSession('s17-kb-export')
test.use({ storageState: session.statePath })
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})
test.afterEach(async ({ context }) => {
  await session.save(context)
})

/** Unikalny sufiks (wzór: `uniq` w s17-model-edit) — filtr karty po PELNEJ nazwie bez strict mode. */
function uniq(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`
}

const DATASET_NAME = 'E2E SC-E7-2-01 Rocznik GUS'
const C_PASSWORD = 'wd-test-user-c1'
/** Długa nazwa wariantu (SCENARIOS: 120 znaków — ellipsis + tooltip); unikalny sufiks w środku,
 * bo karty filtrujemy po pełnej nazwie, a prefiks „E2E SC-E7-2-01” łapie też bazę zasiewu (T10). */
const LONG_NAME =
  `E2E SC-E7-2-01 ${uniq()} ${'Rocznik statystyczny Rzeczypospolitej Polskiej '.repeat(4)}`.slice(
    0,
    120,
  )
/** Budżet eksportu w UI (R-KB-01: ≤ 3 min, z zapasem na wolniejszą maszynę). */
const EXPORT_UI_BUDGET_MS = 420_000
const STOP_BUDGET_MS = 30_000

type Shared = { token: string; datasetId: string }

// Zasiew raz na plik (parsowanie GUS ~10 min) — reset bazy K9 biegnie raz w `global-setup.ts`,
// więc dane kolejnych testów są nietknięte; token to string, wywołania API używają `request`
// bieżącego testu.
let shared: Promise<Shared> | undefined
function seeded(request: Parameters<typeof apiLogin>[0]): Promise<Shared> {
  const pending = (shared ??= (async () => {
    let token = await apiLogin(request)
    // Ponowienie (retry w nowym workerze) przesiewa od nowa — duplikat nazwy („…(1)”) wywalał
    // strict mode filtrów kart po nazwie (T10 bieg 2).
    await deleteDatasetsNamed(request, token, DATASET_NAME)
    const datasetId = await seedExportDataset(request, token, DATASET_NAME, async () => {
      // Parsowanie GUS ma budżet 20 min, a TTL tokenu 15 min — odświeżanie wewnątrz zasiewu.
      token = await apiLogin(request)
      return token
    })
    return { token, datasetId }
  })())
  // Porażka zasiewu nie może zatruć kolejnych testów cache'em odrzuconej obietnicy (T10):
  // reset pozwala następnemu testowi zasiew powtórzyć; warunek tożsamości chroni nowy zasiew.
  void pending.catch(() => {
    if (shared === pending) shared = undefined
  })
  return pending
}

/** Wiersz paska zadań danego rodzaju (CONTRACT §7: data-testid + data-task-kind). */
function taskRow(page: Page, kind: 'export' | 'import'): Locator {
  return page.locator(`[data-testid="kb-task-row"][data-task-kind="${kind}"]`)
}

/** Procent z tekstu wiersza („41%”); -1 gdy procentu jeszcze nie ma. */
function rowPercent(text: string): number {
  const match = /(\d+)\s*%/.exec(text)
  return match === null ? -1 : Number(match[1]!)
}

/** Szacunek „ok. X MB” przeliczony na MB (przecinek dziesiętny, GB → 1024 MB). */
function estimateMb(text: string): number {
  const match = /ok\.\s*([\d.,]+)\s*(kB|MB|GB)/.exec(text)
  expect(match, `szacunek rozmiaru w tekście: ${JSON.stringify(text)}`).not.toBeNull()
  const value = Number(match![1]!.replace(',', '.'))
  const unit = match![2]!
  return unit === 'GB' ? value * 1024 : unit === 'kB' ? value / 1024 : value
}

/** Element podsumowania „Do paczki trafią: …” — jednoznaczny w dialogu (nota o kluczach
 * też mówi o rozmiarze, więc szacunek czytamy wyłącznie z tej linii). */
function estimateLine(dialog: Locator): Locator {
  return dialog.getByText(/Do paczki trafią:/)
}

/**
 * Krok 1–2: menu ⋮ karty bazy → pozycja „Eksportuj” (CONTRACT §7) → dialog. Pierwsza asercja
 * pozycji to miejsce, w którym test jest CZERWONY na bazie bez implementacji UI.
 */
async function openExportDialog(page: Page, datasetName: string): Promise<Locator> {
  await page.getByRole('button', { name: `Menu bazy wiedzy ${datasetName}` }).click()
  const menu = page.getByRole('menu')
  await expect(menu).toBeVisible()
  const item = menu.getByRole('menuitem', { name: 'Eksportuj' })
  await expect(item, 'pozycja „Eksportuj” w menu bazy (SC-E7-2-01 krok 1)').toBeVisible()
  await item.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog, 'dialog eksportu (SC-E7-2-01 krok 2)').toBeVisible()
  return dialog
}

test('SC-E7-2-01: eksport „Rocznik GUS” z wektorami — dialog, pasek, pobranie, link i F5', async ({
  page,
  request,
  browser,
}) => {
  // Zasiew korpusu (~10 min) + eksport (~3 min) + kroki UI (krok 7: drugie pobranie ~74 MB).
  test.setTimeout(1_800_000)
  await seeded(request)

  // Sesja z storageState (logowanie raz na plik w beforeAll) — od razu lista baz; wiersze
  // paska z poprzednich testów pliku (storageState przenosi localStorage) czyszczone.
  await page.goto('/datasets')
  await clearKbTaskRows(page)
  await expect(page.getByTestId('dataset-card').filter({ hasText: DATASET_NAME })).toBeVisible()

  // Krok 1–2: pozycja „Eksportuj”, dialog z podsumowaniem i przełącznikiem „Dołącz wektory”.
  const dialog = await openExportDialog(page, DATASET_NAME)
  await expect(
    page.getByRole('dialog', { name: `Eksportuj „${DATASET_NAME}”` }),
    'dosłowna nazwa dialogu eksportu (SC-E7-2-01 krok 2)',
  ).toBeVisible()
  await expect(dialog.getByText(/2\s*pliki/), '2 pliki korpusu').toBeVisible()
  await expect(dialog.getByText(CHUNK_WORD_RE)).toBeVisible()
  await expect(estimateLine(dialog)).toBeVisible()
  const vectorsSwitch = dialog.getByRole('switch', { name: 'Dołącz wektory' })
  await expect(vectorsSwitch, 'przełącznik domyślnie włączony').toBeChecked()
  await expect(dialog.getByText(/nie zawiera kluczy/), 'nota o braku kluczy').toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E7-2-01 krok 2 — dialog eksportu')

  // Krok 3: wyłączenie i włączenie „Dołącz wektory” zmienia szacunek rozmiaru.
  const withVectorsMb = estimateMb(await estimateLine(dialog).innerText())
  await vectorsSwitch.click()
  await expect
    .poll(async () => estimateMb(await estimateLine(dialog).innerText()), {
      message: 'szacunek bez wektorów jest mniejszy',
      timeout: 15_000,
    })
    .toBeLessThan(withVectorsMb)
  await vectorsSwitch.click()
  await expect
    .poll(async () => estimateMb(await estimateLine(dialog).innerText()), {
      message: 'szacunek z wektorami wraca do wartości wyjściowej',
      timeout: 15_000,
    })
    .toBeGreaterThan(withVectorsMb - 0.5)

  // Krok 4: „Eksportuj” zamyka dialog i pokazuje wiersz paska z etapem, licznikiem i procentem.
  // Świeży token PRZED startem eksportu (TTL 15 min od zasiewu potrafi minąć na wolnym hoście;
  // logowanie PO starcie zjada pierwsze sekundy biegu zadania i próbki postępu wychodzą puste).
  const progressToken = await apiLogin(request)
  const progressHeaders = { authorization: `Bearer ${progressToken}` }
  const exportResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/api\/wd\/v1\/datasets\/[^/]+\/export$/.test(new URL(response.url()).pathname),
  )
  await dialog.getByRole('button', { name: 'Eksportuj' }).click()
  await expect(dialog).toBeHidden()
  const exportRef = ((await (await exportResponse).json()) as { data: { task_id: string } }).data
  // Próbki postępu w trakcie eksportu. Wiersz paska odświeża `GET /tasks/{id}` co 2 s
  // (taskStore), a na szybkim stosie testowym eksport (R-KB-01: ≤ 3 min na produkcji) dobiega
  // MIĘDZY dwoma odświeżeniami — pomiar z biegu T11: wiersz pokazuje jedno plateau (np. 95%
  // cztery razy) i koniec, więc „procent w wierszu rośnie” jest tu nieobserwowalne. Rosnący
  // postęp dowodzi się więc u ŹRÓDŁA: `GET /tasks/{id}` próbkowane co 150 ms łapie etapy
  // (files 0–0,1 → chunks 0,1–0,4 → vectors 0,4–0,95 → finalize 1,0), a wiersz pokazuje, że
  // ten postęp w ogóle dochodzi do użytkownika jako procent. Sampler startuje od razu po 202.
  const apiProgress: number[] = []
  let apiDone = false
  const sampleApiProgress = (async (): Promise<void> => {
    while (!apiDone) {
      const response = await request.get(
        `${process.env.WD_E2E_API_URL}/api/wd/v1/tasks/${exportRef.task_id}`,
        { headers: progressHeaders },
      )
      const body = (await response.json()) as { data: { status: string; progress: number } }
      apiProgress.push(body.data.progress)
      if (body.data.status !== 'queued' && body.data.status !== 'running') apiDone = true
      else await new Promise((resolve) => setTimeout(resolve, 150))
    }
  })()
  const row = taskRow(page, 'export').filter({ hasText: DATASET_NAME })
  await expect(row, 'wiersz eksportu w pasku zadań').toBeVisible()
  await expect(row.getByText('Eksport', { exact: false })).toBeVisible()
  // Licznik etapu i procent w wierszu sprawdzane, gdy wiersz zdąży pokazać stan `running`.
  // Od T5 (DEC-350, wektory jako HEX zamiast VEC_ToText) eksport tego korpusu kończy się w < 2 s,
  // czyli przed pierwszym odpytaniem paska (co 2 s) — wiersz przechodzi z „W kolejce” wprost
  // w „Gotowe” i stanu `running` nie da się zaobserwować (próba: 8 × queued → done po ~2,1 s).
  // Wzrost postępu dowodzi wtedy próbnik API (niżej), a render licznika/procentu w trakcie biegu
  // pokrywa TaskRow.test.tsx.
  const rowPercents: number[] = []
  let counterSeen = false
  await expect
    .poll(
      async () => {
        const status = await row.getAttribute('data-task-status')
        const percent = rowPercent(await row.innerText())
        if (status === 'running' && percent >= 0) rowPercents.push(percent)
        if (status === 'running' && /\d+\s*\/\s*\d+/.test(await row.innerText())) counterSeen = true
        return status
      },
      {
        message: 'eksport dochodzi do końca (próbki procentu zbierane w trakcie biegu)',
        timeout: EXPORT_UI_BUDGET_MS,
      },
    )
    .toBe('done')
  apiDone = true
  await sampleApiProgress
  // Obserwowany `running` (wolniejszy host) → wiersz ma pokazać i licznik etapu, i procent.
  if (rowPercents.length > 0 || counterSeen) {
    expect(counterSeen, 'licznik etapu w wierszu w trakcie eksportu').toBe(true)
    expect(rowPercents.length, 'procent postępu w wierszu w trakcie eksportu').toBeGreaterThan(0)
  }
  expect(
    apiProgress.length,
    'backend raportuje postęp zadania eksportu (`WdTask.progress` w GET /tasks/{id})',
  ).toBeGreaterThan(1)
  for (let index = 1; index < apiProgress.length; index += 1) {
    expect(
      apiProgress[index]!,
      `postęp backendu nie maleje (${apiProgress.map((value) => value.toFixed(2)).join(' → ')})`,
    ).toBeGreaterThanOrEqual(apiProgress[index - 1]!)
  }
  expect(
    apiProgress[apiProgress.length - 1]!,
    `postęp backendu rośnie (${apiProgress.map((value) => value.toFixed(2)).join(' → ')})`,
  ).toBeGreaterThan(apiProgress[0]!)
  await expectNoLayoutDefects(page, 'SC-E7-2-01 krok 4 — pasek zadań w trakcie eksportu')

  // Krok 5: koniec — „Gotowe · X MB · link ważny do <data godz.>”, „Pobierz”, „Kopiuj link”.
  await expect(row).toHaveAttribute('data-task-status', 'done', { timeout: EXPORT_UI_BUDGET_MS })
  await expect(row.getByText(/Gotowe · \d+(?:[.,]\d+)?\s*MB/), 'rozmiar paczki w MB').toBeVisible()
  await expect(row.getByText(/link ważny do \d/), 'termin linku z datą').toBeVisible()
  await expect(row.getByRole('button', { name: 'Pobierz' })).toBeVisible()
  await expect(row.getByRole('button', { name: 'Kopiuj link' })).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E7-2-01 krok 5 — wiersz „Gotowe”')

  // Krok 6: „Pobierz” — przeglądarka pobiera paczkę o nazwie i rozmiarze z wyniku zadania.
  // Świeże logowanie: token z zasiewu (TTL 15 min) bywa nieważny po ~17 min od początku pliku.
  const task = await waitTask(request, await apiLogin(request), exportRef.task_id, 60_000)
  const fileName = task.result?.file_name ?? ''
  expect(fileName, 'file_name z wyniku eksportu').toMatch(/\.wdkb\.zip$/)
  const downloadPromise = page.waitForEvent('download')
  await row.getByRole('button', { name: 'Pobierz' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename(), 'nazwa pobranego pliku').toBe(fileName)
  const savedPath = await download.path()
  expect(statSync(savedPath).size, 'rozmiar pobranego pliku = size_bytes').toBe(
    task.result?.size_bytes ?? -1,
  )

  // Krok 7: „Kopiuj link”, otwarcie w nowym kontekście BEZ sesji — pobieranie działa bez
  // logowania. Treść schowka czytamy przez spy na `execCommand` (stos HTTP — wzór s21);
  // init-script wymaga nawigacji, więc strona jest przeładowana przed klikiem (to zarazem
  // wstępna próba kroku 8).
  await page.addInitScript(execCommandCopySpy())
  await page.reload()
  await expect(taskRow(page, 'export').filter({ hasText: DATASET_NAME })).toBeVisible()
  await row.getByRole('button', { name: 'Kopiuj link' }).click()
  const copied = await copiedText(page)
  expect(copied, 'schowek dostaje link pobrania').toContain('/api/wd/v1/exports/')
  const linkContext = await browser.newContext({
    // Kontekst celowo bez storageState (jawny `undefined` — Playwright 1.63 dziedziczy opcje
    // `test.use`, a test ma sprawdzić pobieranie BEZ logowania) — link ma działać bez sesji.
    baseURL: process.env.WD_E2E_BASE_URL,
    storageState: undefined,
  })
  try {
    const linkPage = await linkContext.newPage()
    const consoleErrors = watchConsoleErrors(linkPage)
    const linkDownload = linkPage.waitForEvent('download')
    await linkPage.evaluate((url) => {
      const anchor = document.createElement('a')
      anchor.href = url
      document.body.appendChild(anchor)
      anchor.click()
    }, new URL(copied, page.url()).toString())
    const linkDownloaded = await linkDownload
    expect(linkDownloaded.suggestedFilename(), 'nazwa z linku bez sesji').toBe(fileName)
    const linkSaved = await linkDownloaded.path()
    expect(statSync(linkSaved).size, 'rozmiar z linku bez sesji = size_bytes').toBe(
      task.result?.size_bytes ?? -1,
    )
    expect(consoleErrors, 'błędy konsoli w kontekście linku').toEqual([])
  } finally {
    await linkContext.close()
  }

  // Krok 8: F5 na liście baz — wiersz eksportu nadal w pasku (localStorage + API).
  await page.reload()
  const rowAfterReload = taskRow(page, 'export').filter({ hasText: DATASET_NAME })
  await expect(rowAfterReload, 'wiersz eksportu przetrwał F5').toBeVisible()
  await expect(rowAfterReload).toHaveAttribute('data-task-status', 'done')
})

test('SC-E7-2-01 wariant ciemny: dialog i wiersz „Gotowe” w ciemnym motywie (kroki 2, 4, 5)', async ({
  page,
  request,
}) => {
  test.setTimeout(900_000)
  await seeded(request)

  await page.goto('/datasets')
  await clearKbTaskRows(page)
  await expect(page.getByTestId('dataset-card').filter({ hasText: DATASET_NAME })).toBeVisible()

  // Ciemny motyw (przełącznik w nagłówku — wzór: s10-admin-access).
  await page.getByRole('button', { name: 'Tryb kolorów' }).click()
  await page.getByRole('menuitem', { name: 'Ciemny' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-mui-color-scheme', 'dark')

  // Krok 2 w ciemnym: dialog z podsumowaniem i przełącznikiem.
  const dialog = await openExportDialog(page, DATASET_NAME)
  await expect(estimateLine(dialog)).toBeVisible()
  await expect(dialog.getByRole('switch', { name: 'Dołącz wektory' })).toBeChecked()
  await expectNoLayoutDefects(page, 'SC-E7-2-01 krok 2 — dialog eksportu (ciemny)')

  // Krok 4: start eksportu — wiersz w pasku.
  await dialog.getByRole('button', { name: 'Eksportuj' }).click()
  await expect(dialog).toBeHidden()
  const row = taskRow(page, 'export').filter({ hasText: DATASET_NAME })
  await expect(row).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E7-2-01 krok 4 — pasek zadań (ciemny)')

  // Krok 5 w ciemnym: „Gotowe” z terminem linku i akcjami.
  await expect(row).toHaveAttribute('data-task-status', 'done', { timeout: EXPORT_UI_BUDGET_MS })
  await expect(row.getByText(/Gotowe · \d+(?:[.,]\d+)?\s*MB/), 'rozmiar paczki w MB').toBeVisible()
  await expect(row.getByText(/link ważny do \d/), 'termin linku z datą').toBeVisible()
  await expect(row.getByRole('button', { name: 'Pobierz' })).toBeVisible()
  await expect(row.getByRole('button', { name: 'Kopiuj link' })).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E7-2-01 krok 5 — wiersz „Gotowe” (ciemny)')
})

test.describe('SC-E7-2-01 wariant 390 px', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('dialog pełnoekranowy, pasek bez wad układu, Stop zamyka zadanie', async ({
    page,
    request,
  }) => {
    test.setTimeout(600_000)
    await seeded(request)

    await page.goto('/datasets')
    await clearKbTaskRows(page)
    await expect(page.getByTestId('dataset-card').filter({ hasText: DATASET_NAME })).toBeVisible()

    // Dialog < 600 px jest pełnoekranowy (08 §7.15(a)).
    const dialog = await openExportDialog(page, DATASET_NAME)
    const box = await dialog.boundingBox()
    expect(box, 'dialog ma wymiar okna 390 px (pełny ekran)').not.toBeNull()
    expect(box!.width, 'szerokość dialogu = szerokość okna').toBeGreaterThanOrEqual(385)
    await expect(dialog.getByRole('switch', { name: 'Dołącz wektory' })).toBeChecked()
    await expectNoLayoutDefects(page, 'SC-E7-2-01 wariant 390 px — dialog eksportu')

    // Pasek zadań na telefonie: nazwa w jednej linii, postęp i akcje w drugiej (08 §7.15).
    // Geometrię dwóch linii ocenia QA-UI na zrzutach; strażnik układu maszynowo łapie te same
    // defekty (nachodzące/ucięte etykiety, zasłonięte przyciski).
    await dialog.getByRole('button', { name: 'Eksportuj' }).click()
    await expect(dialog).toBeHidden()
    const row = taskRow(page, 'export').filter({ hasText: DATASET_NAME })
    await expect(row).toBeVisible()
    await expectNoLayoutDefects(page, 'SC-E7-2-01 wariant 390 px — pasek zadań')

    // Sprzątanie zadania: Stop zamyka eksport (zachowanie Stop to SC-E7-2-04 krok 5).
    await row.getByRole('button', { name: 'Stop' }).click()
    await expect(row).toHaveAttribute('data-task-status', 'cancelled', { timeout: STOP_BUDGET_MS })
  })
})

test('SC-E7-2-01 wariant EN: pozycja, dialog i przełącznik po angielsku (kroki 1–2)', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  await seeded(request)

  await page.goto('/datasets')
  await expect(page.getByTestId('dataset-card').filter({ hasText: DATASET_NAME })).toBeVisible()

  // Język EN z nagłówka (wzór: s10-admin-access); po asercjach powrót na Polski.
  await page.getByRole('button', { name: 'Język' }).click()
  await page.getByRole('menuitem', { name: 'English' }).click()

  await page.getByRole('button', { name: `Dataset menu ${DATASET_NAME}` }).click()
  const menu = page.getByRole('menu')
  await expect(menu).toBeVisible()
  const exportItem = menu.getByRole('menuitem', { name: 'Export' })
  await expect(exportItem, 'pozycja „Export” w menu (EN)').toBeVisible()
  await exportItem.click()
  const dialog = page.getByRole('dialog', {
    name: new RegExp(`Export “${escapeRegExp(DATASET_NAME)}”`),
  })
  await expect(dialog, 'dialog eksportu po angielsku').toBeVisible()
  await expect(dialog.getByRole('switch', { name: 'Include vectors' })).toBeChecked()
  await expectNoLayoutDefects(page, 'SC-E7-2-01 wariant EN — dialog eksportu')
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()

  // Powrót na Polski, żeby dalsze testy pliku widziały etykiety PL.
  await page.getByRole('button', { name: 'Language' }).click()
  await page.getByRole('menuitem', { name: 'Polski' }).click()
  await expect(page.getByRole('button', { name: `Menu bazy wiedzy ${DATASET_NAME}` })).toBeVisible()
})

test('SC-E7-2-01 wariant długa nazwa (120 znaków): ellipsis i tooltip w dialogu', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const token = await apiLogin(request)
  // Pusta baza o 120-znakowej nazwie: wariant sprawdza skrócenie i tooltip, nie eksport.
  const longId = await createDataset(request, token, LONG_NAME)
  try {
    // Sesja z storageState (logowanie raz na plik w beforeAll).
    await page.goto('/datasets')
    await expect(
      // Pełna, unikalna nazwa: prefiks „E2E SC-E7-2-01” przy retry/wielu bazach łapał też
      // inne karty (strict mode violation — T10 bieg 2).
      page.getByTestId('dataset-card').filter({ hasText: LONG_NAME }),
    ).toBeVisible()

    const dialog = await openExportDialog(page, LONG_NAME)
    // Pełna nazwa w nazwie dostępnej dialogu — dosłowny tytuł PL (CONTRACT §7: „Eksportuj „<nazwa>””).
    await expect(
      page.getByRole('dialog', { name: `Eksportuj „${LONG_NAME}”` }),
      'pełna nazwa w nazwie dostępnej dialogu',
    ).toBeVisible()
    // Widoczny tytuł jest skrócony wielokropkiem — brak ellipsis wyłapuje strażnik układu.
    await expectNoLayoutDefects(page, 'SC-E7-2-01 wariant długa nazwa — dialog eksportu')
    // Tooltip z pełną nazwą po najechaniu na widoczny tytuł.
    await dialog.getByText(LONG_NAME).first().hover()
    await expect(page.getByRole('tooltip')).toContainText(LONG_NAME, { timeout: 5_000 })
    await dialog.getByRole('button', { name: 'Anuluj' }).click()
    await expect(dialog).toBeHidden()
  } finally {
    await deleteDataset(request, token, longId)
  }
})

/** „Pobierz”/inny przycisk wiersza w całości w oknie (defekt QA-UI: wypchnięte poza kartę). */
async function expectButtonWithinViewport(page: Page, button: Locator): Promise<void> {
  const box = await button.boundingBox()
  const viewport = page.viewportSize()
  expect(box, 'przycisk ma wymiar (widoczny w wierszu)').not.toBeNull()
  expect(viewport, 'strona ma ustawiony viewport').not.toBeNull()
  expect(box!.x, 'przycisk mieści się w oknie — lewa krawędź ≥ 0').toBeGreaterThanOrEqual(0)
  expect(
    box!.x + box!.width,
    `przycisk mieści się w oknie — prawa krawędź ≤ ${viewport!.width}`,
  ).toBeLessThanOrEqual(viewport!.width)
}

test('SC-E7-2-01 wariant długa nazwa: wiersz paska zadań bez wad układu (defekt QA-UI)', async ({
  page,
  request,
}) => {
  test.setTimeout(600_000)
  const token = await apiLogin(request)
  // Własna nazwa (inny uniq niż dialogowy LONG_NAME): filtry po PEŁNEJ nazwie się nie spotykają.
  const barName = `E2E SC-E7-2-01 ${uniq()} ${'Bardzo długa nazwa bazy wiedzy '.repeat(4)}`.slice(
    0,
    120,
  )
  await deleteDatasetsNamed(request, token, barName) // retry-safe (wzór seeded)
  const longId = await createDataset(request, token, barName)
  try {
    // Mały plik z fixtures (bez zasiewu GUS) — wzór seedCorpus: upload, parse, `run = DONE`.
    const pdf = readFileSync(fileURLToPath(new URL('./fixtures/sample.pdf', import.meta.url)))
    const uploaded = await ragOk<{ id: string }[]>(
      request.post(`${process.env.WD_E2E_API_URL}/api/v1/datasets/${longId}/documents`, {
        headers: authHeaders(token),
        multipart: { file: { name: 'sample.pdf', mimeType: 'application/pdf', buffer: pdf } },
      }),
      'POST /datasets/{id}/documents (sample.pdf)',
    )
    const documentId = uploaded[0]!.id
    await ragOk<unknown>(
      request.post(`${process.env.WD_E2E_API_URL}/api/v1/datasets/${longId}/documents/parse`, {
        headers: authHeaders(token),
        data: { document_ids: [documentId] },
      }),
      'POST /datasets/{id}/documents/parse',
    )
    const deadline = Date.now() + 90_000
    for (;;) {
      const listed = await ragOk<{ docs: { run: string }[] }>(
        request.get(
          `${process.env.WD_E2E_API_URL}/api/v1/datasets/${longId}/documents?id=${documentId}`,
          { headers: authHeaders(token) },
        ),
        'GET /datasets/{id}/documents (sample.pdf)',
      )
      const run = listed.docs[0]?.run ?? ''
      if (run === 'DONE' || run === 'FAIL' || run === 'CANCEL') {
        expect(run, 'parsowanie sample.pdf').toBe('DONE')
        break
      }
      expect(Date.now() < deadline, 'parsowanie sample.pdf w budżecie 90 s').toBe(true)
      await new Promise((resolve) => setTimeout(resolve, 1_000))
    }

    await page.goto('/datasets')
    await clearKbTaskRows(page)
    const dialog = await openExportDialog(page, barName)
    await dialog.getByRole('button', { name: 'Eksportuj' }).click()
    await expect(dialog).toBeHidden()
    const row = taskRow(page, 'export').filter({ hasText: barName })
    await expect(row, 'wiersz eksportu w pasku zadań').toBeVisible()
    await expect(row).toHaveAttribute('data-task-status', 'done', { timeout: EXPORT_UI_BUDGET_MS })
    await expect(
      row.getByText(/Gotowe ·/),
      'status „Gotowe · rozmiar · link” w wierszu',
    ).toBeVisible()

    // Desktop: status i przyciski w granicach karty, bez poziomego przewijania strony
    // (strażnik: overflow-page, ucięte etykiety, zasłonięte przyciski).
    await expect(row.getByRole('button', { name: 'Pobierz' })).toBeVisible()
    await expectNoLayoutDefects(page, 'SC-E7-2-01 długa nazwa — wiersz „Gotowe” (desktop)')
    await expectButtonWithinViewport(page, row.getByRole('button', { name: 'Pobierz' }))

    // 390 px: ten sam wiersz — zawinięcie dozwolone, nic poza oknem (nie ucięcia).
    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoLayoutDefects(page, 'SC-E7-2-01 długa nazwa — wiersz „Gotowe” (390 px)')
    await expectButtonWithinViewport(page, row.getByRole('button', { name: 'Pobierz' }))
  } finally {
    await deleteDataset(request, token, longId)
  }
})

test('SC-E7-2-05: uprawnienia — członek zespołu bez „Eksportuj”, superuser przy cudzej bazie', async ({
  request,
  browser,
}) => {
  test.setTimeout(300_000)
  const adminToken = await apiLogin(request)

  // Konto członka zespołu (C) i dwie bazy: zespołowa (właściciel: admin, permission=team)
  // oraz własna C — kontrola pozytywna, że ten sam użytkownik WIDZI „Eksportuj” u siebie.
  const memberEmail = `s17-export-c-${Date.now()}@wd.test`
  const teamName = 'E2E SC-E7-2-05 baza zespołu'
  const memberName = 'E2E SC-E7-2-05 baza C'
  await createUserByApi(request, adminToken, memberEmail, C_PASSWORD, 'SC-E7-2-05 członek')
  const memberToken = await loginToken(request, memberEmail, C_PASSWORD)
  const teamDatasetId = await createDatasetWithPermission(request, adminToken, teamName, 'team')
  const memberDatasetId = await createDataset(request, memberToken, memberName)
  // Kontekst członka BEZ sesji pliku (storageState pliku to admin z `uiSession`; T10): członek
  // loguje się raz formularzem — limiter logowań liczy każdą próbę, więc każdy użytkownik
  // pliku loguje się co najwyżej raz.
  const memberContext = await browser.newContext({
    baseURL: process.env.WD_E2E_BASE_URL,
    locale: 'pl-PL',
    storageState: undefined,
  })
  try {
    // Krok 1: członek zespołu przy bazie zespołowej — menu otwarte, ale BEZ „Eksportuj”.
    const memberPage = await memberContext.newPage()
    const memberErrors = watchConsoleErrors(memberPage)
    await loginViaUiAs(memberPage, memberEmail, C_PASSWORD)
    await memberPage.goto('/datasets')
    await expect(memberPage.getByTestId('dataset-card').filter({ hasText: teamName })).toBeVisible()
    await memberPage.getByRole('button', { name: `Menu bazy wiedzy ${teamName}` }).click()
    const teamMenu = memberPage.getByRole('menu')
    await expect(teamMenu).toBeVisible()
    await expect(teamMenu.getByRole('menuitem', { name: 'Zmień nazwę' })).toBeVisible()
    await expect(
      teamMenu.getByRole('menuitem', { name: 'Eksportuj' }),
      'członek zespołu nie eksportuje cudzej bazy (SC-E7-2-05 krok 1)',
    ).toHaveCount(0)
    await memberPage.keyboard.press('Escape')

    // Kontrola pozytywna: TA sama osoba przy WŁASNEJ bazie „Eksportuj” widzi.
    await memberPage.getByRole('button', { name: `Menu bazy wiedzy ${memberName}` }).click()
    const ownMenu = memberPage.getByRole('menu')
    await expect(
      ownMenu.getByRole('menuitem', { name: 'Eksportuj' }),
      'właściciel widzi „Eksportuj” przy własnej bazie',
    ).toBeVisible()
    await memberPage.keyboard.press('Escape')
    expect(memberErrors, 'błędy konsoli w kontekście członka').toEqual([])

    // Krok 2: superuser (admin z seedu) przy cudzej bazie — „Eksportuj” dostępne.
    const adminContext = await browser.newContext({
      baseURL: process.env.WD_E2E_BASE_URL,
      locale: 'pl-PL',
      storageState: undefined,
    })
    try {
      const adminPage = await adminContext.newPage()
      const consoleErrors = watchConsoleErrors(adminPage)
      await loginViaUi(adminPage)
      await adminPage.goto('/datasets')
      await expect(
        adminPage.getByTestId('dataset-card').filter({ hasText: memberName }),
      ).toBeVisible()
      await adminPage.getByRole('button', { name: `Menu bazy wiedzy ${memberName}` }).click()
      const adminMenu = adminPage.getByRole('menu')
      await expect(
        adminMenu.getByRole('menuitem', { name: 'Eksportuj' }),
        'superuser widzi „Eksportuj” przy cudzej bazie (SC-E7-2-05 krok 2)',
      ).toBeVisible()
      expect(consoleErrors, 'błędy konsoli w kontekście superusera').toEqual([])
    } finally {
      await adminContext.close()
    }
  } finally {
    await memberContext.close()
    // Sprzątanie: bazy przez właścicieli, konto C kaskadowo (wzór: helpers/admin.ts).
    await deleteDataset(request, adminToken, teamDatasetId)
    await deleteDataset(request, memberToken, memberDatasetId)
    await deleteUserByEmail(request, adminToken, memberEmail)
  }
})
