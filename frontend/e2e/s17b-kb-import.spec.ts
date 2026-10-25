// Scenariusze E7-2: import paczki .wdkb.zip w UI (SCENARIOS.md SC-E7-2-02, -03, -04; spec UX
// 08-frontend §7.15(c); kontrakt K19 §3, nazwy i data-testid: CONTRACT E7-2 §7). Dane: baza
// z rocznikiem GUS + DOCX, eksport i pobranie paczki przez API RAZ na plik (zasiew ~10 min);
// import w UI idzie jako użytkownik B (drugi kontekst instalacji A→B w e2e to wariant
// `e2e-real`). Paczki uszkodzone buduje helper (K19 §2 — E7-1f nie ma fixture'ów w repo).
// Testy pliku są zależne w kolejności deklaracji (SC-02 importuje, SC-03 importuje drugi raz)
// — stan wyjściowy SC-03 jest jednak zabezpieczony przez API (retry-safe). Logowanie B raz na
// plik (T10, wzór: `helpers/session.ts` i s17-model-edit): limiter logowań 10/min liczy KAŻDĄ
// próbę, a `uiSession` loguje wyłącznie admina — sesję B składa ten plik na tym samym wzorcu.
import os from 'node:os'
import path from 'node:path'

import type { ConsoleMessage, Locator, Page, Route } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, deleteAllChats, loginViaUi } from './helpers'
import { dropFile } from './helpers/dnd'
import { takeOverConsoleGuard } from './helpers/integrations'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { deleteUserByEmail, watchConsoleErrors } from './helpers/admin'
import {
  buildWdkbZip,
  CHUNK_WORD_RE,
  clearKbTaskRows,
  datasetIdsNamed,
  deleteDatasetsNamed,
  deleteImportSession,
  deleteProviderInstance,
  dropPackageFromUrl,
  ensureImportedDataset,
  exportAndDownloadPackage,
  fakePackageBytes,
  createUserByApi,
  loginToken,
  registerEmbeddingModel,
  seedExportDataset,
  waitTask,
  GUS_PDF_NAME,
  IMPORT_TASK_BUDGET_MS,
  NCBR_DOCX_NAME,
  REEMBED_TASK_BUDGET_MS,
} from './helpers/kbTransfer'

const DATASET_NAME = 'E2E SC-E7-2-02 GUS'
const QUESTION = 'Ile wynosiła liczba ludności Polski w 2023 roku?'
const B_PASSWORD = 'wd-test-user-b1'
/** Model embeddingu o innym wymiarze (fake-llm: 3072) — SC-E7-2-03 krok 3. */
const OTHER_MODEL = 'fake-embed-3072'
const OTHER_DIMENSION = 3072
const STOP_BUDGET_MS = 60_000
/** Trasa porcji wysyłania i jej spowolnienie — pasek „Wysłano a/b MB” pozostaje obserwowalny
 * (prawdziwy backend, wolniejszy wyłącznie przekaz — wzór: s07 Stop). */
const CONTENT_ROUTE = '**/api/wd/v1/dataset-imports/*/content'
const UPLOAD_CHUNK_DELAY_MS = 1_200

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Sesja użytkownika B na plik (T10): plik `storageState` z logowaniem B w `beforeAll`, każdy
 * test startuje z sesją z cookie `wd_refresh` — bez formularza. `uiSession` z `helpers/session.ts`
 * loguje wyłącznie admina (stałe fixture'ów), a testy tego pliku biegną jako B, więc sesję B
 * składa plik na tym samym wzorcu (formularz raz, `afterEach` zapisuje stan po rotacji cookie).
 */
const B_STATE_PATH = path.join(os.tmpdir(), `wd-e2e-s17b-kb-import-${process.pid}-b-state.json`)
test.use({ storageState: B_STATE_PATH })
test.beforeAll(async ({ browser }) => {
  // Własny kontekst na zasiew i logowanie B: fixture `request` (i `playwright.request…`)
  // jest składany z opcji `test.use` — czyta `storageState`, którego plik powstaje dopiero
  // W TYM haku, i jej odczyt (ENOENT) wywala hak przed ciałem, bez komunikatu (T10 diagnoza).
  // Jawny `undefined` wyłącza odczyt (Playwright 1.63 dziedziczy opcje `test.use`).
  const context = await browser.newContext({ storageState: undefined })
  try {
    // Zasiew ma ~15 min (parsowanie GUS + eksport), a domyślny timeout hooka = timeout testu —
    // jawnie podnosimy (wzór: `session.login` w helpers/session.ts); 40 min z zapasem na
    // chwilowe zatory hosta, bo ponowienie haka to kolejny pełny zasiew.
    test.setTimeout(2_400_000)
    const s = await sharedKb(context.request)
    // Logowanie B przez API na ORIGINIE FRONTU (wzór: `apiLoginWithBackoff` w
    // helpers/session.ts): Set-Cookie `wd_refresh` trafia na kontekst jak przy formularzu.
    // Logowanie przez renderer (goto + formularz) w tym haku potrafiło wisieć bez komunikatu
    // na obciążonym hoście — tu jest zero zależności od przeglądarki. Jedna próba wystarcza:
    // limiter liczy per IP+e-mail (CONTRACT E5-2a §4), a e-mail B jest świeży na każdy bieg.
    const base = process.env.WD_E2E_BASE_URL ?? ''
    expect(base, 'brak WD_E2E_BASE_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')
    const login = await context.request.post(`${base}/api/v1/auth/login`, {
      data: { email: s.bEmail, password: B_PASSWORD },
    })
    const loginText = await login.text()
    const loginBody = JSON.parse(loginText) as { code: number; message: string }
    expect(login.status(), `login B: HTTP ${login.status()} — ${loginText}`).toBe(200)
    expect(loginBody.code, `login B: ${loginBody.message}`).toBe(0)
    // Weryfikacja materiału sesji bez renderera: cookie rotacyjne jest w stanie kontekstu.
    const state = await context.storageState()
    expect(
      state.cookies.some((cookie) => cookie.name === 'wd_refresh'),
      'cookie `wd_refresh` po logowaniu B',
    ).toBe(true)
    await context.storageState({ path: B_STATE_PATH })
  } finally {
    await context.close()
  }
})
test.afterEach(async ({ context }) => {
  // Rotacja (C9): refresh przy starcie strony wymienia cookie — kolejny test dostaje świeży
  // stan; kontekst bez cookie `wd_refresh` nie nadpisuje sesji pliku pustym stanem.
  const state = await context.storageState()
  if (state.cookies.some((cookie) => cookie.name === 'wd_refresh')) {
    await context.storageState({ path: B_STATE_PATH })
  }
})

async function slowUploadChunks(route: Route): Promise<void> {
  await sleep(UPLOAD_CHUNK_DELAY_MS)
  await route.continue()
}

/** Oczekiwany błąd sieci porcji przy odciciu (SC-E7-2-04 krok 3): typ sieciowy `net::ERR_`
 * na trasach /api/ — wąsko, tylko zakłócenia transportowe tego scenariusza. */
function isOfflineApiError(message: ConsoleMessage): boolean {
  return message.text().includes('net::ERR_') && message.location().url.includes('/api/')
}

/** Oczekiwany 409 name_conflict ze startu importu (SC-E7-2-03 krok 2). */
function isNameConflictStart(message: ConsoleMessage): boolean {
  return (
    message.text().includes('status of 409') &&
    message.location().url.includes('/dataset-imports/') &&
    message.location().url.endsWith('/start')
  )
}

type SharedKb = {
  gusDatasetId: string
  pkg: Awaited<ReturnType<typeof exportAndDownloadPackage>>
  bEmail: string
  embInstanceId: string
  corruptName: string
}

// Zasiew raz na plik: baza korpusowa + eksport + pobranie paczki + konto B + model 3072.
let shared: Promise<SharedKb> | undefined
function sharedKb(request: Parameters<typeof apiLogin>[0]): Promise<SharedKb> {
  const pending = (shared ??= (async () => {
    let adminToken = await apiLogin(request)
    // Ponowienie (retry w nowym workerze) przesiewa od nowa — duplikat nazwy („…(1)”) wywalał
    // strict mode filtrów kart po nazwie (T10 bieg 2).
    await deleteDatasetsNamed(request, adminToken, DATASET_NAME)
    const gusDatasetId = await seedExportDataset(request, adminToken, DATASET_NAME, async () => {
      // Parsowanie GUS ma budżet 20 min, a TTL tokenu 15 min — odświeżanie wewnątrz zasiewu.
      adminToken = await apiLogin(request)
      return adminToken
    })
    const pkg = await exportAndDownloadPackage(request, adminToken, gusDatasetId, 's17b')
    const bEmail = `s17b-b-${Date.now()}@wd.test`
    await createUserByApi(request, adminToken, bEmail, B_PASSWORD, 'SC-E7-2-02 użytkownik B')
    const embInstanceId = await registerEmbeddingModel(
      request,
      adminToken,
      `s17b-emb-${Date.now()}`,
      OTHER_MODEL,
      OTHER_DIMENSION,
    )
    return {
      gusDatasetId,
      pkg,
      bEmail,
      embInstanceId,
      corruptName: 'E2E SC-E7-2-04 uszkodzona',
    }
  })())
  // Porażka zasiewu nie może zatruć kolejnych testów cache'em odrzuconej obietnicy (T10):
  // reset pozwala następnemu testowi zasiew powtórzyć; warunek tożsamości chroni nowy zasiew.
  void pending.catch(() => {
    if (shared === pending) shared = undefined
  })
  return pending
}

test.afterAll(async ({ browser }) => {
  // Sprzątanie niezależne od przebiegu: instancja modelu, konto B (kaskadowo z jego bazami
  // — wzór: helpers/admin.ts), baza korpusowa admina. Token z zasiewu ma TTL 15 min, a
  // sprzątanie biegnie na końcu pliku — logowanie świeże. Kontekst własny zamiast fixture
  // `request`: przy porażce haka plik sesji nie istnieje i fixture pękłaby na ENOENT.
  if (shared === undefined) return
  const state = await shared.catch(() => null)
  if (state === null) return
  const context = await browser.newContext({ storageState: undefined })
  try {
    const token = await apiLogin(context.request)
    await deleteProviderInstance(context.request, token, state.embInstanceId)
    await deleteUserByEmail(context.request, token, state.bEmail)
    await deleteDataset(context.request, token, state.gusDatasetId)
  } finally {
    await context.close()
  }
})

/** Wiersz paska zadań danego rodzaju (CONTRACT §7: data-testid + data-task-kind). */
function taskRow(scope: Page, kind: 'export' | 'import'): Locator {
  return scope.locator(`[data-testid="kb-task-row"][data-task-kind="${kind}"]`)
}

/** Otwiera dialog importu z listy baz — pierwsza asercja przycisku jest CZERWONA bez UI. */
async function openImportDialog(page: Page): Promise<Locator> {
  const importButton = page.getByRole('button', { name: 'Importuj' })
  await expect(importButton, 'przycisk „Importuj” na liście baz (SC-E7-2-02 krok 1)').toBeVisible()
  await importButton.click()
  const dialog = page.getByRole('dialog', { name: 'Importuj bazę wiedzy' })
  await expect(dialog).toBeVisible()
  return dialog
}

/** Wiersz dokumentu w siatce plików datasetu (wzór: s03-upload-parse). */
function documentRow(page: Page, name: string): Locator {
  return page.getByRole('row').filter({ has: page.getByRole('link', { name }) })
}

test('SC-E7-2-02: import paczki jako użytkownik B — drop, podsumowanie, pasek, otwarcie i czat', async ({
  page,
  request,
}) => {
  // Zasiew (~10 min) + eksport (~3 min) + import UI z wektorami (~3 min) + czat.
  test.setTimeout(1_800_000)
  const s = await sharedKb(request)
  const bToken = await loginToken(request, s.bEmail, B_PASSWORD)
  // Ponowienie testu nie może widzieć bazy z poprzedniej próby (nazwa = nazwa z paczki).
  await deleteDatasetsNamed(request, bToken, DATASET_NAME)

  // Sesja B z storageState (logowanie raz na plik w beforeAll); wiersze paska z poprzednich
  // testów pliku (storageState przenosi localStorage) czyszczone przed filtrami wierszy.
  await page.goto('/datasets')
  await clearKbTaskRows(page)

  // Krok 1: dialog importu — krok 1 „Wybierz plik” + strefa upuszczania.
  const dialog = await openImportDialog(page)
  await expect(dialog.getByRole('button', { name: 'Wybierz plik' })).toBeVisible()
  const dropzone = dialog.getByTestId('kb-import-dropzone')
  await expect(dropzone).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E7-2-02 krok 1 — dialog importu')

  // Krok 2: przeciągnięcie paczki (DataTransfer z bajtami pobranymi w stronie — paczka ~74 MB
  // nie przechodzi przez most CDP); spowolnione porcje robią pasek wysyłania obserwowalnym.
  await page.route(CONTENT_ROUTE, slowUploadChunks)
  const createResponse = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === 'POST' &&
      new URL(candidate.url()).pathname === '/api/wd/v1/dataset-imports',
  )
  await dropPackageFromUrl(page, dropzone, s.pkg.downloadPath, s.pkg.fileName)
  const created = await createResponse
  expect(created.status(), 'POST /dataset-imports (sesja importu)').toBe(201)
  await expect(dialog.getByText(/Wysłano\s+\d/), 'pasek wysyłania').toBeVisible({
    timeout: 30_000,
  })
  await expect(dialog.getByRole('button', { name: 'Anuluj' }), '„Anuluj” aktywny').toBeEnabled()
  // BEZ `unroute` w trakcie wysyłki (diagnoza biegu 3: trace SC-E7-2-02 — pierwszy PUT nigdy
  // nie opuścił strony, dialog zamarł na „Wysłano 0 B”; podejrzane okno wyścigu unroute ↔
  // przekazanie żądania handlerowi trasy). Trasa żyje do końca testu — spowolnione zostają
  // wyłącznie porcje wysyłki.

  // Krok 3: podsumowanie — nazwa z paczki, 2 pliki, chunki, „z wektorami”, data i wersja,
  // model „Zgodny z paczką”.
  const nameField = dialog.getByLabel('Nazwa', { exact: true })
  await expect(nameField, 'nazwa wypełniona z paczki').toHaveValue(DATASET_NAME, {
    timeout: 60_000,
  })
  await expect(dialog.getByText(/2\s*pliki/)).toBeVisible()
  await expect(dialog.getByText(CHUNK_WORD_RE)).toBeVisible()
  await expect(dialog.getByText('z wektorami')).toBeVisible()
  await expect(dialog.getByText(/utworzona/)).toBeVisible()
  await expect(dialog.getByText('Zgodny z paczką')).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E7-2-02 krok 3 — podsumowanie importu')

  // Krok 4: „Importuj” — dialog zamknięty, wiersz importu w pasku, koniec „Gotowe — 2 pliki”.
  const startResponse = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === 'POST' &&
      /\/api\/wd\/v1\/dataset-imports\/[^/]+\/start$/.test(new URL(candidate.url()).pathname),
  )
  await dialog.getByRole('button', { name: 'Importuj' }).click()
  await expect(dialog).toBeHidden()
  const importRef = ((await (await startResponse).json()) as { data: { task_id: string } }).data
  const row = taskRow(page, 'import').filter({ hasText: DATASET_NAME })
  await expect(row, 'wiersz importu w pasku zadań').toBeVisible()
  const task = await waitTask(request, bToken, importRef.task_id, IMPORT_TASK_BUDGET_MS)
  expect(
    task.status,
    `import z wektorami (${task.message}${task.error ? ` — ${task.error.message}` : ''})`,
  ).toBe('done')
  const importedDatasetId = task.result?.dataset_id ?? ''
  expect(importedDatasetId, 'dataset_id z wyniku importu').not.toBe('')
  await expect(row).toHaveAttribute('data-task-status', 'done')
  await expect(row.getByText(/Gotowe — 2 pliki/)).toBeVisible()
  await expect(row.getByText(CHUNK_WORD_RE)).toBeVisible()
  await expect(row.getByRole('button', { name: 'Otwórz' })).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E7-2-02 krok 4 — wiersz importu „Gotowe”')

  // Krok 5: „Otwórz” — dataset: oba pliki „Sukces” (bez parsowania), podgląd PDF się otwiera.
  await row.getByRole('button', { name: 'Otwórz' }).click()
  await expect(page).toHaveURL(new RegExp(`/dataset/files/${importedDatasetId}`))
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible({ timeout: 30_000 })
  for (const fileName of [GUS_PDF_NAME, NCBR_DOCX_NAME]) {
    const fileRow = documentRow(page, fileName)
    await expect(fileRow, `wiersz dokumentu ${fileName}`).toBeVisible({ timeout: 60_000 })
    await expect(fileRow.locator('[data-testid^="status-cell-"]')).toHaveText('Sukces', {
      timeout: 60_000,
    })
  }
  await page.getByRole('link', { name: GUS_PDF_NAME }).click()
  const chunksPage = page.getByTestId('chunks-page')
  await expect(chunksPage, 'podgląd PDF (strona chunków)').toBeVisible({ timeout: 30_000 })
  await expect(chunksPage.getByRole('navigation', { name: 'Ścieżka nawigacji' })).toContainText(
    GUS_PDF_NAME,
  )

  // Krok 6: czat z tą bazą (fake-llm) — odpowiedź z cytatem; modal cytatu z fragmentem
  // rocznika (retrieval słowami pytania trafia w GUS — wzór raportu NCBR nie zawiera
  // fraz o ludności).
  const chatId = await createChat(request, bToken, {
    name: 'E2E SC-E7-2-02 czat',
    datasetIds: [importedDatasetId],
  })
  await page.goto(`/chat/${chatId}`)
  await page.getByPlaceholder('Wpisz pytanie…').fill(QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()
  const answer = page.getByTestId('message-assistant').last()
  await expect(answer).toContainText('Na podstawie źródeł', { timeout: 30_000 })
  const chip = page.getByRole('button', { name: 'Cytowanie 1' })
  await expect(chip).toBeVisible()
  await chip.click()
  const citeDialog = page.getByRole('dialog').filter({ has: page.getByTestId('cite-content') })
  await expect(citeDialog, 'modal cytatu').toBeVisible()
  // Nazwa dokumentu jest nagłówkiem dialogu (DialogTitle = doc_name z cytatu), a `cite-content`
  // pełną treścią chunku rocznika. Retrieval słowami pytania trafia w tablice Kościołów
  // (przypis „c” o liczbie ludności): chunk z nagłówkiem strony 191 (EN) albo 192 (PL) —
  // wspólny niezmiennik to zdanie o ludności Polski 2023 z liczbą 37636,5 tys. (PL „,5 tys.”,
  // EN „.5 thousand”).
  await expect(citeDialog, 'nazwa pliku w nagłówku dialogu cytatu').toContainText(GUS_PDF_NAME)
  await expect(citeDialog.getByTestId('cite-content')).toContainText(
    /liczba ludności Polski w końcu 2023|37636[.,]\d+/,
  )

  // Sprzątanie: czaty i zaimportowana baza należą do B.
  await deleteAllChats(request, bToken)
  await deleteDataset(request, bToken, importedDatasetId)
})

test('SC-E7-2-03: konflikt nazwy i model niezgodny', async ({ page, request }) => {
  test.setTimeout(1_800_000)
  const s = await sharedKb(request)
  const bToken = await loginToken(request, s.bEmail, B_PASSWORD)
  // Stan wyjściowy kroku 1: baza o nazwie paczki istnieje (z SC-E7-2-02 albo tu przez API —
  // retry-safe, bo sprzątanie SC-E7-2-02 usuwa jej bazę).
  await ensureImportedDataset(request, bToken, s.pkg, DATASET_NAME)

  // Oczekiwany 409 name_conflict ze startu importu (krok 2) — wąski wyjątek strażnika.
  const consoleErrors = takeOverConsoleGuard(page, [isNameConflictStart])

  // Sesja B z storageState (logowanie raz na plik w beforeAll); wiersze paska czyszczone.
  await page.goto('/datasets')
  await clearKbTaskRows(page)
  const dialog = await openImportDialog(page)
  const nameField = dialog.getByLabel('Nazwa', { exact: true })

  // Krok 1: ta sama paczka drugi raz (wariant setInputFiles) — sugerowana nazwa z sufiksem
  // „(import RRRR-MM-DD)”; przy zaproponowanej wolnej nazwie ostrzeżenie „Nazwa zajęta” NIE
  // pokazuje się (T2 p. 4 i), wraca dopiero po wpisaniu zajętej nazwy z paczki (krok 2).
  await dialog.locator('input[type="file"]').setInputFiles(s.pkg.filePath)
  await expect(nameField).toHaveValue(/import \d{4}-\d{2}-\d{2}/, { timeout: 60_000 })
  const suggestedName = await nameField.inputValue()
  await expect(
    dialog.getByText(/jest zajęta/),
    'przy zaproponowanej wolnej nazwie brak ostrzeżenia o zajętej nazwie',
  ).toBeHidden()

  // Krok 2: zajęta nazwa wpisana ręcznie — ostrzeżenie wraca; po „Importuj” błąd pod polem
  // z propozycją do kliknięcia.
  await nameField.fill(DATASET_NAME)
  await expect(dialog.getByText(/jest zajęta/), 'ostrzeżenie o zajętej nazwie').toBeVisible()
  const conflictResponse = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === 'POST' &&
      /\/api\/wd\/v1\/dataset-imports\/[^/]+\/start$/.test(new URL(candidate.url()).pathname),
  )
  await dialog.getByRole('button', { name: 'Importuj' }).click()
  expect((await conflictResponse).status(), 'start z zajętą nazwą → 409 name_conflict').toBe(409)
  // `kbTransfer.error.name_conflict` (PL): „Nazwa jest już zajęta.” — w odróżnieniu od
  // ostrzeżenia z kroku 1 („Nazwa „X” jest zajęta”) między „jest” a „zajęta” stoi „już”.
  await expect(dialog.getByText(/już zajęta/), 'błąd pod polem Nazwa').toBeVisible()
  const proposal = dialog.getByText(suggestedName)
  await expect(proposal, 'propozycja sugerowanej nazwy do kliknięcia').toBeVisible()
  await proposal.click()
  await expect(nameField, 'propozycja wypełnia pole').toHaveValue(suggestedName)

  // Krok 3: inny model embeddingów (inny wymiar) — ostrzeżenie o ponownym przeliczeniu
  // z liczbą chunków i oszacowaniem tokenów (MINORS T3c: nie tylko słowa, liczby sperte).
  await dialog.getByRole('combobox', { name: 'Model embeddingów' }).click()
  await page.getByRole('option', { name: OTHER_MODEL }).click()
  await expect(
    dialog.getByText(/Wszystkie chunki zostaną przeliczone wybranym modelem: \d/),
    'liczba chunków w ostrzeżeniu re-embedu',
  ).toBeVisible()
  // Tokeny idą zapisem kompaktowym `formatCompact` („ok. 1,9 mln”, „74 tys.”) — regex
  // akceptuje sufiksy tys./mln. i separatory, zawsze z liczbą przed „tokenów/tokens”.
  await expect(
    dialog.getByText(/ok\. \d[\d\u00a0., ]*(?:\s?(?:tys|mln)\.?)? token(ów|s)/),
    'oszacowanie tokenów z liczbą (estimated_reembed_tokens)',
  ).toBeVisible()

  // Krok 4: „Importuj” — etap „Embedding n/N” w pasku, koniec „Gotowe”, czat z cytatem.
  const startResponse = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === 'POST' &&
      /\/api\/wd\/v1\/dataset-imports\/[^/]+\/start$/.test(new URL(candidate.url()).pathname),
  )
  await dialog.getByRole('button', { name: 'Importuj' }).click()
  await expect(dialog).toBeHidden()
  const importRef = ((await (await startResponse).json()) as { data: { task_id: string } }).data
  const row = taskRow(page, 'import').filter({ hasText: suggestedName })
  await expect(row, 'wiersz importu w pasku').toBeVisible()
  await expect(row.getByText(/Embedding\s+\d+\//), 'etap ponownego embeddingu').toBeVisible({
    timeout: 120_000,
  })
  // Świeże logowanie: ponowny embedding ma budżet 12 min, a TTL tokenu to 15 min od logowania
  // na początku testu (zasiew + import + UI podjadały większość) — token z startu bywał
  // nieważny w trakcie odpytywania (T10).
  const task = await waitTask(
    request,
    await loginToken(request, s.bEmail, B_PASSWORD),
    importRef.task_id,
    REEMBED_TASK_BUDGET_MS,
  )
  expect(
    task.status,
    `import z ponownym embeddingiem (${task.message}${task.error ? ` — ${task.error.message}` : ''})`,
  ).toBe('done')
  expect(task.result?.reembedded, 'niezgodny model → ponowny embedding').toBe(true)
  const reembeddedDatasetId = task.result?.dataset_id ?? ''
  expect(reembeddedDatasetId, 'dataset_id z wyniku importu').not.toBe('')
  await expect(row).toHaveAttribute('data-task-status', 'done')
  await expect(row.getByText(/Gotowe/), 'stan końcowy „Gotowe” w kroku 4').toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E7-2-03 krok 4 — wiersz importu „Gotowe”')

  const chatId = await createChat(request, bToken, {
    name: 'E2E SC-E7-2-03 czat',
    datasetIds: [reembeddedDatasetId],
  })
  await page.goto(`/chat/${chatId}`)
  await page.getByPlaceholder('Wpisz pytanie…').fill(QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()
  const answer = page.getByTestId('message-assistant').last()
  await expect(answer).toContainText('Na podstawie źródeł', { timeout: 30_000 })
  const chip = page.getByRole('button', { name: 'Cytowanie 1' })
  await expect(chip).toBeVisible()
  await chip.click()
  const citeDialog = page.getByRole('dialog').filter({ has: page.getByTestId('cite-content') })
  await expect(citeDialog, 'modal cytatu').toBeVisible()
  // Jak w SC-E7-2-02 krok 6: nazwa pliku w nagłówku dialogu, a w `cite-content` niezmiennik
  // obu wariantów chunku (strony 191/192) — przypis o liczbie ludności Polski 2023.
  await expect(citeDialog, 'nazwa pliku w nagłówku dialogu cytatu').toContainText(GUS_PDF_NAME)
  await expect(citeDialog.getByTestId('cite-content')).toContainText(
    /liczba ludności Polski w końcu 2023|37636[.,]\d+/,
  )

  // Sprzątanie: czat i druga baza należą do B (baza stanu wyjściowego czeka na afterAll).
  await deleteAllChats(request, bToken)
  await deleteDataset(request, bToken, reembeddedDatasetId)
  expect(consoleErrors, 'błędy konsoli poza oczekiwanym 409 name_conflict').toEqual([])
})

test('SC-E7-2-04 a (kroki 1–2): paczka z niezgodną sumą i plik podmieniony na .wdkb.zip', async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const s = await sharedKb(request)
  const bToken = await loginToken(request, s.bEmail, B_PASSWORD)
  await page.goto('/datasets')
  const dialog = await openImportDialog(page)
  const dropzone = dialog.getByTestId('kb-import-dropzone')
  await expect(dropzone).toBeVisible()

  // Krok 1: poprawny ZIP wg K19 §2, wpis files/<sha> z niezgodną sumą → checksum_mismatch;
  // zamiast podsumowania lista błędów po polsku (komunikat K19 renderowany dosłownie z API,
  // 08 §7.15(c): „Suma SHA-256 wpisu … niezgodna z manifestem") i „Wybierz inny plik”.
  const corrupt = buildWdkbZip({ datasetName: s.corruptName, corruptChecksum: true })
  await dropFile(page, dropzone, corrupt, 'uszkodzona.wdkb.zip', 'application/zip')
  await expect(dialog.getByText(/niezgodna z manifestem/), 'lista błędów po polsku').toBeVisible({
    timeout: 60_000,
  })
  await expect(dialog.getByRole('button', { name: 'Wybierz inny plik' })).toBeVisible()
  await expectNoLayoutDefects(page, 'SC-E7-2-04 krok 1 — lista błędów paczki')
  expect(
    await datasetIdsNamed(request, bToken, s.corruptName),
    'uszkodzona paczka nie tworzy bazy',
  ).toEqual([])

  // Krok 2: plik .txt przemianowany na .wdkb.zip — komunikat z API (`errors[].message`,
  // 08 §7.15(c); decyzja TL w briefie T11: UI zostaje, asercja na fragment komunikatu API —
  // `validate.py` walidatora paczki; od E67-z2 UI pokazuje własny komunikat zamiast tego z API).
  await dialog.getByRole('button', { name: 'Wybierz inny plik' }).click()
  await expect(dropzone, 'powrót do wyboru pliku').toBeVisible()
  await dialog.locator('input[type="file"]').setInputFiles({
    name: 'nie-paczka.wdkb.zip',
    mimeType: 'application/zip',
    buffer: fakePackageBytes(),
  })
  await expect(
    dialog.getByText('To nie jest poprawna paczka bazy wiedzy (.wdkb.zip).'),
    'komunikat o uszkodzonym archiwum',
  ).toBeVisible({ timeout: 60_000 })
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(dialog).toBeHidden()
})

test('SC-E7-2-04 b (krok 3): odcicie sieci na 5 s — „Wznawianie…” i dokończenie bez ponownego wyboru', async ({
  page,
  request,
}) => {
  test.setTimeout(600_000)
  const s = await sharedKb(request)
  const bToken = await loginToken(request, s.bEmail, B_PASSWORD)
  const consoleErrors = takeOverConsoleGuard(page, [isOfflineApiError])

  await page.goto('/datasets')
  const dialog = await openImportDialog(page)
  const dropzone = dialog.getByTestId('kb-import-dropzone')

  await page.route(CONTENT_ROUTE, slowUploadChunks)
  const createResponse = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === 'POST' &&
      new URL(candidate.url()).pathname === '/api/wd/v1/dataset-imports',
  )
  await dropPackageFromUrl(page, dropzone, s.pkg.downloadPath, s.pkg.fileName)
  const importId = ((await (await createResponse).json()) as { data: { import_id: string } }).data
    .import_id
  try {
    await expect(dialog.getByText(/Wysłano\s+\d/), 'wysyłanie w toku').toBeVisible({
      timeout: 30_000,
    })
    // Odcicie sieci na 5 s — jedyne sleep w scenariuszu (brief T3: zero waitForTimeout
    // poza odcięciem sieci). Backoff uploadSession to 1 s/2 s/4 s; MINORS T3d: trzecia
    // próba wznowienia może paść tuż przed powrotem sieci (margines < 1 s) — wtedy sesja
    // czeka w `paused` na „Wznów”. Test akceptuje oba tory: wznowienie samo albo klik
    // „Wznów”, gdy przycisk się pojawi.
    await page.context().setOffline(true)
    await expect(dialog.getByText('Wznawianie…'), 'komunikat wznawiania').toBeVisible({
      timeout: 4_500,
    })
    await sleep(5_000)
    await page.context().setOffline(false)
    const summaryField = dialog.getByLabel('Nazwa', { exact: true })
    const resumeButton = dialog.getByRole('button', { name: 'Wznów' })
    await expect
      .poll(async () => (await resumeButton.isVisible()) || (await summaryField.isVisible()), {
        message: 'po powrocie sieci: podsumowanie albo „Wznów”',
        timeout: 30_000,
      })
      .toBe(true)
    if (await resumeButton.isVisible()) {
      await resumeButton.click()
    }
    // Po powrocie sieci wysyłanie kończy się bez ponownego wyboru pliku — podsumowanie.
    await expect(summaryField).toBeVisible({ timeout: 120_000 })
    await expectNoLayoutDefects(page, 'SC-E7-2-04 krok 3 — podsumowanie po wznowieniu')
  } finally {
    await page.unroute(CONTENT_ROUTE)
    await deleteImportSession(request, bToken, importId)
  }
  expect(consoleErrors, 'błędy konsoli poza oczekiwanymi (odcięcie sieci)').toEqual([])
})

test('SC-E7-2-04 c (kroki 4–5): Stop w pasku zatrzymuje import i eksport', async ({
  page,
  request,
  browser,
}) => {
  test.setTimeout(900_000)
  const s = await sharedKb(request)
  const bToken = await loginToken(request, s.bEmail, B_PASSWORD)

  await page.goto('/datasets')
  await clearKbTaskRows(page)
  const dialog = await openImportDialog(page)
  const dropzone = dialog.getByTestId('kb-import-dropzone')
  const createResponse = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === 'POST' &&
      new URL(candidate.url()).pathname === '/api/wd/v1/dataset-imports',
  )
  await dropPackageFromUrl(page, dropzone, s.pkg.downloadPath, s.pkg.fileName)
  const importId = ((await (await createResponse).json()) as { data: { import_id: string } }).data
    .import_id
  const nameField = dialog.getByLabel('Nazwa', { exact: true })
  await expect(nameField, 'podsumowanie importu').toBeVisible({ timeout: 120_000 })
  const chosenName = await nameField.inputValue()

  // Krok 4: Stop w trakcie importu — „Anulowano”, baza nie pojawia się na liście.
  const startResponse = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === 'POST' &&
      /\/api\/wd\/v1\/dataset-imports\/[^/]+\/start$/.test(new URL(candidate.url()).pathname),
  )
  await dialog.getByRole('button', { name: 'Importuj' }).click()
  await expect(dialog).toBeHidden()
  const importRef = ((await (await startResponse).json()) as { data: { task_id: string } }).data
  const importRow = taskRow(page, 'import').filter({ hasText: chosenName })
  await expect(importRow, 'wiersz importu w pasku').toBeVisible()
  await importRow.getByRole('button', { name: 'Stop' }).click()
  await expect(importRow).toHaveAttribute('data-task-status', 'cancelled', {
    timeout: STOP_BUDGET_MS,
  })
  await expect(importRow.getByText('Anulowano')).toBeVisible()
  const stopped = await waitTask(request, bToken, importRef.task_id, STOP_BUDGET_MS)
  expect(stopped.status, 'zadanie importu po Stop').toBe('cancelled')
  expect(
    await datasetIdsNamed(request, bToken, chosenName),
    'anulowany import nie zostawia bazy',
  ).toEqual([])
  await deleteImportSession(request, bToken, importId)

  // Krok 5: Stop w trakcie eksportu (superuser startuje eksport z UI własnej bazy) —
  // „Anulowano”, brak „Pobierz”.
  const adminContext = await browser.newContext({
    // Jawny `undefined`: Playwright 1.63 dziedziczy opcje `test.use` (tu sesja B), a krok 5
    // biegnie jako superuser przez formularz (T10).
    baseURL: process.env.WD_E2E_BASE_URL,
    locale: 'pl-PL',
    storageState: undefined,
  })
  try {
    const adminPage = await adminContext.newPage()
    const consoleErrors = watchConsoleErrors(adminPage)
    await loginViaUi(adminPage)
    await adminPage.goto('/datasets')
    // Superuser widzi też bazy użytkowników: po SC-E7-2-03 baza B o tej samej nazwie czeka
    // na afterAll, więc kartę wskazujemy po id bazy źródłowej (link karty = /dataset/files/<id>),
    // nie po nazwie (strict mode violation przy 2 kartach).
    const sourceCard = adminPage
      .getByTestId('dataset-card')
      .filter({ has: adminPage.locator(`a[href$="/dataset/files/${s.gusDatasetId}"]`) })
    await expect(sourceCard).toBeVisible()
    await sourceCard.getByRole('button', { name: `Menu bazy wiedzy ${DATASET_NAME}` }).click()
    await adminPage.getByRole('menuitem', { name: 'Eksportuj' }).click()
    const exportDialog = adminPage.getByRole('dialog')
    await expect(exportDialog).toBeVisible()
    const exportStart = adminPage.waitForResponse(
      (candidate) =>
        candidate.request().method() === 'POST' &&
        /\/api\/wd\/v1\/datasets\/[^/]+\/export$/.test(new URL(candidate.url()).pathname),
    )
    await exportDialog.getByRole('button', { name: 'Eksportuj' }).click()
    await expect(exportDialog).toBeHidden()
    expect((await exportStart).status(), 'start eksportu → 202').toBe(202)
    const exportRow = taskRow(adminPage, 'export').filter({ hasText: DATASET_NAME })
    await expect(exportRow, 'wiersz eksportu w pasku').toBeVisible()
    await exportRow.getByRole('button', { name: 'Stop' }).click()
    await expect(exportRow).toHaveAttribute('data-task-status', 'cancelled', {
      timeout: STOP_BUDGET_MS,
    })
    await expect(exportRow.getByText('Anulowano')).toBeVisible()
    await expect(exportRow.getByRole('button', { name: 'Pobierz' })).toHaveCount(0)
    expect(consoleErrors, 'błędy konsoli w kontekście superusera').toEqual([])
  } finally {
    await adminContext.close()
  }
})
