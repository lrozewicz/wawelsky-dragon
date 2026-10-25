// T10 (QA V12-2-1, work/qa/V12-2-1/WYNIKI-QA.md): defekty D2a — surowy `progress_msg`
// w zakładce „Logi” (IngestionLogDialog nie tłumaczył), D2b — prefiks klasy wyjątku po
// „[ERROR] ” blokował dopasowanie P19–P28, D3 — `aria-describedby` na wyłączonym „Save”
// w „Dodaj model” (defekt zgłoszony w EN; wariant PL pokrywa s28-v12-hints „SC-V12-08 a”).
// Testy pisane PRZED poprawką — czerwony bieg: work/wp/V12-2/reports/T10-red.log.
// Wzorce: s28-v12-messages.spec.ts (wstrzykiwanie logu przez `page.route`, sesja),
// s28-v12-hints.spec.ts (zasiew instancji modeli).
import { expect, test } from './fixtures'
import { apiLogin, createDataset, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { createInstanceWithModels, deleteInstance, setProfileLanguage } from './helpers/models'
import type { InstanceModelSpec } from './helpers/models'
import { uiSession } from './helpers/session'

const SHOTS = process.env.WD_SHOTS_DIR ?? ''

const session = uiSession('s28-v12-qafix')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(240_000)

let token = ''
let datasetId = ''
let corpus: SeededCorpus

// Logowanie w OSOBNYM haku PRZED hakiem używającym `request` (pułapka z s17b: fixture
// `request` czyta `storageState`, który powstaje dopiero w `session.login`).
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

test.beforeAll(async ({ request }) => {
  token = await apiLogin(request)
  datasetId = await createDataset(request, token, `E2E V12-2 T10 logi ${Date.now()}`)
  corpus = await seedCorpus(request, token, {
    datasetName: `E2E V12-2 T10 błąd ${Date.now()}`,
    documentName: 'e2e-t10-log.txt',
    documentBody: 'Notatka do scenariusza logu błędu SC-V12-06 k3 (T10, QA V12-2-1 D2b).',
  })
})

test.afterAll(async ({ request }) => {
  await deleteDataset(request, token, datasetId)
  await deleteDataset(request, token, corpus.datasetId)
})

test.afterEach(async ({ context }) => {
  await session.save(context)
})

async function shot(page: import('@playwright/test').Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Koperta RAGFlow zwracana przez przechwyconą trasę (HTTP 200 — błędy idą w `code`). */
function envelope(code: number, data: unknown): string {
  return JSON.stringify({ code, message: 'success', data })
}

/** Wiersz listy zadań zakładki „Logi” (kształt `IngestionLog`, kontrakt §Fakty API). */
function logRow(progressMsg: string): Record<string, unknown> {
  return {
    id: 'log-e2e-1',
    kb_id: datasetId,
    document_id: 'doc-e2e-1',
    document_name: 'e2e-t10-log.xlsx',
    document_type: 'xlsx',
    document_suffix: 'xlsx',
    task_type: 'file',
    process_begin_at: '2026-10-17 08:00:00',
    process_duration: 12.5,
    operation_status: '4',
    progress: 1,
    progress_msg: progressMsg,
    create_time: 1790000000000,
  }
}

test('SC-V12-09 p.2 UI PL: zakładka Logi — „Pokaż log” tłumaczy „Auto metadata: 0 fields”', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  // Wstrzyknięta lista zadań i szczegół logu (endpoint z `ingestionLogQueryOptions`) —
  // bez czekania na realną ingestję (QA D2a: surowy wpis w dialogu zakładki Logi).
  const row = logRow('')
  await page.route(/\/api\/v1\/datasets\/[^/]+\/ingestions\?/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: envelope(0, { logs: [row], total: 1 }),
    }),
  )
  await page.route(/\/api\/v1\/datasets\/[^/]+\/ingestions\/log-e2e-1$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: envelope(
        0,
        logRow('08:00:01 Task has been received.\n08:00:02 Auto metadata: 0 fields'),
      ),
    }),
  )
  await page.goto(`/dataset/logs/${datasetId}`)
  await page.getByRole('button', { name: 'Pokaż log e2e-t10-log.xlsx' }).click()
  const dialog = page.getByRole('dialog', { name: 'Log przetwarzania' })
  await expect(dialog).toBeVisible()
  // Treść po polsku (P1 i P14), surowy wpis nie przechodzi.
  await expect(dialog).toContainText('08:00:01 Zadanie przyjęte.')
  await expect(dialog).toContainText('Metadane automatyczne: nie znaleziono wartości')
  await expect(dialog).not.toContainText('Auto metadata: 0 fields')
  await expect(dialog).not.toContainText('Task has been received.')
  await expectNoLayoutDefects(page, 'T10 D2a: dialog logu zakładki Logi (PL, 1280)')
  await shot(page, 'qafix-log-tab-pl-1280')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(dialog).toBeVisible()
  await expectNoLayoutDefects(page, 'T10 D2a: dialog logu zakładki Logi (PL, 390)')
  await shot(page, 'qafix-log-tab-pl-390')
})

test('SC-V12-06 k3 UI PL: log błędu — klasa wyjątku zdjęta, treść po polsku bez „CorruptedFile”', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.route(/\/api\/v1\/datasets\/[^/]+\/documents\?/, async (route) => {
    const response = await route.fetch()
    const body = (await response.json()) as { data: { docs: { progress_msg: string }[] } }
    for (const doc of body.data.docs) {
      doc.progress_msg = [
        '08:00:01 Task has been received.',
        '08:00:04 [ERROR] CorruptedFile: File is corrupted or unreadable (.docx): file content does not match its extension',
        '08:00:05 [ERROR] SomethingNovel: entirely unknown trouble',
      ].join('\n')
    }
    await route.fulfill({ response, json: body })
  })
  await page.goto(`/dataset/files/${corpus.datasetId}`)
  await page.getByTestId(`status-log-${corpus.documentId}`).click()
  const logDialog = page.getByRole('dialog', { name: `— ${corpus.documentName}` })
  await expect(logDialog).toBeVisible()
  // P21 z prefiksem klasy: treść po polsku, nazwa klasy zdjęta; reason (część dynamiczna)
  // zostaje dosłownie. Nieznana treść z klasą — dosłownie (klasa zostaje).
  await expect(logDialog).toContainText(
    '08:00:04 [ERROR] Plik jest uszkodzony lub nieczytelny (.docx): file content does not match its extension',
  )
  await expect(logDialog).not.toContainText('CorruptedFile')
  await expect(logDialog).toContainText('08:00:05 [ERROR] SomethingNovel: entirely unknown trouble')
  await expect(logDialog).toContainText('08:00:01 Zadanie przyjęte.')
  await expectNoLayoutDefects(page, 'T10 D2b: dialog logu parsowania z klasą błędu (PL)')
  await shot(page, 'qafix-error-log-pl-1280')
})

test('SC-V12-08 k1 UI EN i PL: „Save” z pustą nazwą ogłasza powód przez aria-describedby', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const instanceName = `E2E S28 T10 ${Date.now()}`
  const models: InstanceModelSpec[] = [
    { name: `fake-chat-${Date.now()}`, modelType: 'chat', maxTokens: 8192 },
  ]
  const instanceId = await createInstanceWithModels(request, token, instanceName, models)
  try {
    // PL: powód pod przyciskiem powiązany aria-describedby (regresja — wariant w s28-v12-hints).
    await page.goto('/user-setting/model')
    await page.getByTestId(`instance-item-${instanceId}`).click()
    await expect(
      page.getByRole('heading', { name: `Modele instancji: ${instanceName}` }),
    ).toBeVisible()
    await page.getByRole('button', { name: 'Dodaj model' }).click()
    const dialogPl = page.getByRole('dialog', { name: 'Dodaj model' })
    await expect(dialogPl).toBeVisible()
    const savePl = dialogPl.getByRole('button', { name: 'Zapisz' })
    await expect(savePl).toBeDisabled()
    await expect(savePl).toHaveAttribute('aria-describedby', 'add-model-save-reason')
    await expect(dialogPl.getByText('Uzupełnij: Nazwa modelu')).toBeVisible()
    await shot(page, 'qafix-add-model-reason-pl-1280')

    // EN: defekt D3 zgłoszony właśnie w tym wariancie (QA V12-2-1, zrzut SC08-…-en).
    await setProfileLanguage(request, token, 'en')
    await page.goto('/user-setting/model')
    await page.getByTestId(`instance-item-${instanceId}`).click()
    await page.getByRole('button', { name: 'Add model' }).click()
    const dialogEn = page.getByRole('dialog', { name: 'Add model' })
    await expect(dialogEn).toBeVisible()
    const saveEn = dialogEn.getByRole('button', { name: 'Save' })
    await expect(saveEn).toBeDisabled()
    await expect(saveEn).toHaveAttribute('aria-describedby', 'add-model-save-reason')
    await expect(dialogEn.getByText('Fill in: Model name')).toBeVisible()
    await expectNoLayoutDefects(page, 'T10 D3: dialog „Add model” z powodem (EN)')
    await shot(page, 'qafix-add-model-reason-en-1280')
  } finally {
    await setProfileLanguage(request, token, 'pl')
    await deleteInstance(request, token, instanceId)
  }
})
