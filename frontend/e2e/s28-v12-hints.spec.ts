// SC-V12-08 (work/wp/V12/SCENARIOS.md, brief T5 V12-2): „Wiem, dlaczego nie mogę zapisać /
// co robi »Prześlij«”. Nieaktywny „Zapisz” ma widoczny powód pod przyciskiem, powiązany
// atrybutem `aria-describedby`, a po częściowym błędzie uploadu główny przycisk zmienia
// etykietę na „Prześlij ponownie nieudane (N)” z podpowiedzią, że udane nie pójdą drugi raz.
// Testy pisane PRZED implementacją (czerwone z właściwej przyczyny: brak powodu i etykiety).
// Uwaga: dialog „Dodaj/Edytuj model” nie ma pola klucza API (klucz należy do instancji,
// dialog `InstanceDialog` — poza zakresem plików briefu), więc powód bierzemy z realnych
// warunków `canSave`: pusta nazwa, okno kontekstu poza zakresem.
// Wzorzec: s17-model-edit.spec.ts (sesja, zasiew instancji), s28-v12-messages.spec.ts (skrót WP).
import type { Page } from '@playwright/test'
import type { APIRequestContext, Locator } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createDataset } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { createInstanceWithModels, deleteInstance } from './helpers/models'
import type { InstanceModelSpec } from './helpers/models'
import { uiSession } from './helpers/session'

const SHOTS = process.env.WD_SHOTS_DIR ?? ''

const session = uiSession('s28-v12-hints')
test.use({ storageState: session.statePath, colorScheme: 'light' })
test.setTimeout(180_000)

/** Unikalny sufiks — nazwy modeli są unikalne w rejestrze tenantu (duplikat → 102, K13 §4). */
function uniq(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`
}

/**
 * Współdzielony token admina na cały bieg pliku (wzór s17): limiter logowań liczy każdą próbę
 * (10/min per IP+e-mail) i jest współdzielony z całym biegiem verify-full.
 */
let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

/** Zasoby do sprzątania po każdym teście (afterEach). */
const createdInstances: string[] = []
const createdDatasets: string[] = []

test.afterEach(async ({ request }) => {
  const token = await adminToken(request)
  for (const id of createdInstances.splice(0)) {
    await deleteInstance(request, token, id)
  }
  for (const id of createdDatasets.splice(0)) {
    await deleteDataset(request, token, id)
  }
})

// Logowanie w OSOBNYM haku PRZED hakiem używającym `request` (pułapka z s17b: fixture `request`
// czyta `storageState`, który powstaje dopiero w `session.login`).
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

test.afterEach(async ({ context }) => {
  await session.save(context)
})

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS !== '') await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

/** Zasiew instancji z modelami + rejestracja do sprzątania (wzór s17). */
async function seedInstance(
  request: APIRequestContext,
  token: string,
  models: InstanceModelSpec[],
): Promise<{ instanceId: string; instanceName: string }> {
  const instanceName = `E2E S28 ${uniq()}`
  const instanceId = await createInstanceWithModels(request, token, instanceName, models)
  createdInstances.push(instanceId)
  return { instanceId, instanceName }
}

/** Baza wiedzy przez API + rejestracja do sprzątania. */
async function seedDataset(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<string> {
  const datasetId = await createDataset(request, token, name)
  createdDatasets.push(datasetId)
  return datasetId
}

/** Ustawienia → Modele z wybraną instancją scenariusza (wzór s17). */
async function openModelsPage(page: Page, instanceId: string, instanceName: string): Promise<void> {
  await page.goto('/user-setting/model')
  await page.getByTestId(`instance-item-${instanceId}`).click()
  await expect(
    page.getByRole('heading', { name: `Modele instancji: ${instanceName}` }),
  ).toBeVisible()
}

/**
 * Powód nieaktywnego przycisku (SC-V12-08 k1): `aria-describedby` prowadzi do widocznego
 * elementu z dokładnie tym tekstem. Zwraca tekst pomocniczy do asercji zniknięcia.
 */
async function expectDisabledReason(save: Locator, reason: string): Promise<Locator> {
  await expect(save).toBeDisabled()
  await expect(save).toHaveAttribute('aria-describedby', /.+/)
  const hintId = await save.getAttribute('aria-describedby')
  const hint = save.page().locator(`#${hintId ?? ''}`)
  await expect(hint).toHaveText(reason)
  return hint
}

/** Po poprawie: przycisk aktywny, atrybut i tekst powodu znikają. */
async function expectReasonGone(save: Locator, hint: Locator): Promise<void> {
  await expect(save).toBeEnabled()
  expect(await save.getAttribute('aria-describedby'), 'atrybut powodu zdjęty').toBeNull()
  await expect(hint).toHaveCount(0)
}

/** Pole okna kontekstu w dialogach modeli (kontrakt E5-H8c §1: `getByLabel` przez `for`/`id`). */
function maxTokensField(page: Page) {
  return page.getByLabel('Okno kontekstu (tokeny)')
}

/** Przycisk ✎ w wierszu siatki modeli (kontrakt: aria-label „Edytuj model <nazwa>”). */
function editButton(page: Page, modelName: string) {
  return page
    .getByRole('row')
    .filter({ hasText: modelName })
    .getByRole('button', { name: `Edytuj model ${modelName}` })
}

test('SC-V12-08 a: „Dodaj model” — Zapisz nieaktywny z powodem „Uzupełnij/Popraw” i aria-describedby', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const token = await adminToken(request)
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: `fake-chat-${uniq()}`, modelType: 'chat', maxTokens: 8192 },
  ])
  await openModelsPage(page, instanceId, instanceName)

  await page.getByRole('button', { name: 'Dodaj model' }).click()
  const dialog = page.getByRole('dialog', { name: 'Dodaj model' })
  await expect(dialog).toBeVisible()
  const save = dialog.getByRole('button', { name: 'Zapisz' })

  // Świeży dialog: brak wymaganego pola (nazwa pusta) → powód pod przyciskiem (k1).
  await expectDisabledReason(save, 'Uzupełnij: Nazwa modelu')
  await expect(save).toHaveText('Zapisz')

  // Nazwa uzupełniona, ale drugi wymagany warunek `canSave` zepsuty (okno kontekstu < 1024) →
  // powód mówi, CO poprawić.
  await dialog.getByLabel('Nazwa modelu').fill(`fake-chat-${uniq()}`)
  await maxTokensField(page).fill('100')
  const hint = await expectDisabledReason(save, 'Popraw: Okno kontekstu (tokeny)')
  await shot(page, 's28-add-model-reason-1280')
  await expectNoLayoutDefects(page, 'dialog „Dodaj model” z powodem nieaktywnego Zapisz')

  // Poprawa → powód znika, przycisk aktywny.
  await maxTokensField(page).fill('4096')
  await expectReasonGone(save, hint)
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(dialog).toBeHidden()
})

test('SC-V12-08 b: „Edytuj model” — puste wymagane okno kontekstu daje powód', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const token = await adminToken(request)
  const chat = `fake-chat-${uniq()}`
  const { instanceId, instanceName } = await seedInstance(request, token, [
    { name: chat, modelType: 'chat', maxTokens: 8192 },
  ])
  await openModelsPage(page, instanceId, instanceName)

  await editButton(page, chat).click()
  const dialog = page.getByRole('dialog', { name: `Edytuj model: ${chat}` })
  await expect(dialog).toBeVisible()
  const save = dialog.getByRole('button', { name: 'Zapisz' })
  await expect(save).toBeEnabled()

  // Wyczyszczone wymagane pole → „Uzupełnij: …”; zła wartość → „Popraw: …”.
  await maxTokensField(page).fill('')
  const hint = await expectDisabledReason(save, 'Uzupełnij: Okno kontekstu (tokeny)')
  await maxTokensField(page).fill('50')
  await expectDisabledReason(save, 'Popraw: Okno kontekstu (tokeny)')

  await maxTokensField(page).fill('4096')
  await expectReasonGone(save, hint)
  await dialog.getByRole('button', { name: 'Anuluj' }).click()
  await expect(dialog).toBeHidden()
})

test('SC-V12-08 c: konfiguracja datasetu — „Brak zmian do zapisania” i „Popraw: Klucz”', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const token = await adminToken(request)
  const datasetName = `E2E S28 konfiguracja ${uniq()}`
  const datasetId = await seedDataset(request, token, datasetName)
  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.getByRole('heading', { name: datasetName })).toBeVisible()
  const save = page.getByRole('button', { name: 'Zapisz' })

  // Nic nie zmieniono → „Zapisz” wyłączony z powodem (k1: użytkownik wie, dlaczego).
  const hint = await expectDisabledReason(save, 'Brak zmian do zapisania')

  // Wartość błędna: pole metadanych bez klucza → „Zapisz” dalej wyłączony, powód wskazuje pole.
  await page.getByRole('button', { name: '+ Pole' }).click()
  await expectDisabledReason(save, 'Popraw: Klucz')
  await shot(page, 's28-config-reason-1280')
  await expectNoLayoutDefects(page, 'konfiguracja datasetu z powodem nieaktywnego Zapisz')

  // Uzupełnienie klucza: formularz ma zmiany i bez błędów → przycisk aktywny.
  await page.getByRole('textbox', { name: 'Klucz' }).fill('autor')
  await expectReasonGone(save, hint)
})

test('SC-V12-08 d: upload — „Prześlij ponownie nieudane (1)”, podpowiedź i ponowienie tylko nieudanego', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const token = await adminToken(request)
  const datasetName = `E2E S28 upload ${uniq()}`
  const datasetId = await seedDataset(request, token, datasetName)
  await page.goto(`/dataset/files/${datasetId}`)
  await expect(page.getByRole('heading', { name: datasetName })).toBeVisible()

  await page.getByTestId('files-add').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  // Bez parsowania — scenariusz bada sam dialog i liczbę żądań uploadu, nie workera.
  await dialog.getByTestId('upload-parse-toggle').click()
  const bytes = (name: string): Buffer =>
    Buffer.from(`Zawartość próbki ${name} dla SC-V12-08 d.`, 'utf8')
  await dialog.getByTestId('upload-input').setInputFiles([
    { name: 'pierwszy.txt', mimeType: 'text/plain', buffer: bytes('pierwszy') },
    // Plik odrzucany przez serwer po rozszerzeniu (jak w s28-v12-messages: kod 500).
    { name: 'bledny.exe', mimeType: 'application/octet-stream', buffer: bytes('bledny') },
    { name: 'trzeci.txt', mimeType: 'text/plain', buffer: bytes('trzeci') },
  ])
  await expect(dialog.getByText('pierwszy.txt')).toBeVisible()
  await expect(dialog.getByText('bledny.exe')).toBeVisible()
  await expect(dialog.getByText('trzeci.txt')).toBeVisible()

  await page.getByTestId('upload-start').click()
  const summary = dialog.getByTestId('upload-summary')
  await expect(summary).toHaveText('Przesłano 2 z 3', { timeout: 60_000 })

  // Krok 2 scenariusza: etykieta przycisku mówi, CO się zrobi ponownie (i czego NIE).
  const start = page.getByTestId('upload-start')
  await expect(start).toHaveText('Prześlij ponownie nieudane (1)')
  await expect(start).toHaveAttribute('aria-describedby', /.+/)
  const hintId = await start.getAttribute('aria-describedby')
  const hint = page.locator(`#${hintId ?? ''}`)
  await expect(hint).toContainText('nie zostaną')
  await shot(page, 's28-upload-retry-1280')
  await expectNoLayoutDefects(page, 'dialog uploadu z przyciskiem „Prześlij ponownie nieudane (1)”')

  // Klik wysyła WYŁĄCZNIE nieudany plik — dokładnie jedno żądanie POST dokumentu.
  let uploads = 0
  const countUpload = (req: import('@playwright/test').Request): void => {
    if (req.method() === 'POST' && /\/documents$/.test(req.url())) uploads += 1
  }
  page.on('request', countUpload)
  // Koniec ponowienia = odpowiedź na POST pliku z błędem (teksty dialogu się wtedy nie zmieniają:
  // serwer odrzuca .exe nadal, więc podsumowanie zostaje „2 z 3”, a etykieta dalej oferuje
  // ponowienie; przycisk po pełnym sukcesie wyłączają s03/s16b — T15b).
  const retryResponse = page.waitForResponse(
    (res) => res.request().method() === 'POST' && /\/documents$/.test(res.url()),
    { timeout: 60_000 },
  )
  await start.click()
  await retryResponse
  await expect(summary).toHaveText('Przesłano 2 z 3')
  await expect(start).toHaveText('Prześlij ponownie nieudane (1)')
  await expect(start).toBeEnabled()
  expect(uploads, 'liczba żądań uploadu po ponowieniu').toBe(1)
})

test.describe('SC-V12-08 e: powód nieaktywnego Zapisz w ciemnym motywie', () => {
  test.use({ colorScheme: 'dark' })

  test('390: powód mieści się w oknie (zrzut ciemny)', async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const token = await adminToken(request)
    const datasetId = await seedDataset(request, token, `E2E S28 ciemny 390 ${uniq()}`)
    await page.goto(`/dataset/configuration/${datasetId}`)
    const save = page.getByRole('button', { name: 'Zapisz' })
    const hint = await expectDisabledReason(save, 'Brak zmian do zapisania')
    await expect(hint).toBeVisible()
    // Zrzut kadruje stopkę z powodem — bez przewinięcia kadr pokazuje górę długiego formularza.
    await save.scrollIntoViewIfNeeded()
    await page.waitForTimeout(300)
    await shot(page, 's28-config-390-dark')
    await expectNoLayoutDefects(page, 'konfiguracja 390 ciemna z powodem Zapisz')
  })

  test('1280: powód widoczny i czytelny (zrzut ciemny)', async ({ page, request }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    const token = await adminToken(request)
    const datasetId = await seedDataset(request, token, `E2E S28 ciemny 1280 ${uniq()}`)
    await page.goto(`/dataset/configuration/${datasetId}`)
    const save = page.getByRole('button', { name: 'Zapisz' })
    await expectDisabledReason(save, 'Brak zmian do zapisania')
    await save.scrollIntoViewIfNeeded()
    await page.waitForTimeout(300)
    await shot(page, 's28-config-1280-dark')
    await expectNoLayoutDefects(page, 'konfiguracja 1280 ciemna z powodem Zapisz')
  })
})
