// Scenariusz SC-E67-06 (work/wp/E67-z/SCENARIOS.md, WP E67-z1b, brief T2): metadane — użytkownik
// wie, kiedy działają. Kroki objęte tym plikiem: k1 (zdanie w dialogu „Zastosować zmiany do
// istniejących plików?”), k4 (pusty „Value” → błąd „Podaj wartość”, brak zapisu), k5 (chip warunku
// nad polem pytania czatu otwiera edycję filtra), k6 (podpis/tooltip przy wygaszonych trybach w
// teście retrievalu), k7 (podpowiedź trybu „Automatyczny” widoczna bez przewijania) oraz błąd
// zapisu pól metadanych pokazany przy polu (MINOR E6-1b T4(2), 08 §7.14 U5). Kroki k2–k3 należą do
// T1 (backend, DEC-348) i nie są tu testowane.
// Testy pisane PRZED implementacją (T3): na bieżącym kodzie niezrealizowane kroki są czerwone
// z właściwej przyczyny (brak zdania / błędu / chipa / podpisu), nie z błędu setupu.
// Wzorce: s25-metadata-config.spec.ts (konfiguracja, dialog), s25-metadata-filter.spec.ts
// (kreator filtra w czacie i teście retrievalu), helpers/session.ts (jedno logowanie na plik).
import type { APIRequestContext, APIResponse, Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'
import { apiLogin, createChat, createDataset, deleteAllChats, seedCorpus } from './helpers'
import { deleteDataset } from './helpers/files'
import { expectNoLayoutDefects } from './helpers/layout'
import { openRetrievalTab } from './helpers/retrieval'
import { uiSession } from './helpers/session'

const API_URL = process.env.WD_E2E_API_URL ?? ''

const APPLY_TITLE = 'Zastosować zmiany do istniejących plików?'
const APPLY_SENTENCE =
  'Metadane powstają przy parsowaniu — wybierz „Zastosuj i parsuj ponownie”, żeby objęły wgrane pliki.'
const MODE_GROUP = 'Tryb filtra metadanych'
const FILTER_SECTION = 'Filtr metadanych'
const DOC_BODY =
  'Raport o stanie środowiska w Krakowie opisuje jakość powietrza, wód oraz zieleni miejskiej.'

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow (jak `helpers.ts`): HTTP 200 + `code 0`, inaczej `expect` rzuca. */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

function uniq(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`
}

// Token admina współdzielony w pliku: limiter logowań liczy KAŻDĄ próbę (wzór: s25-*).
let adminTokenPromise: Promise<string> | undefined
function adminToken(request: APIRequestContext): Promise<string> {
  adminTokenPromise ??= apiLogin(request)
  return adminTokenPromise
}

const session = uiSession('s27-e67b-sc06')
test.use({ storageState: session.statePath })
test.setTimeout(120_000)
test.beforeAll(async ({ browser }) => {
  await session.login(browser)
})

/** Datasety do sprzątania po każdym teście; czaty sprzątamy hurtem (lista czatów zaczyna od pustej). */
const cleanupDatasets: string[] = []
test.afterEach(async ({ context, request }) => {
  const token = await adminToken(request)
  await deleteAllChats(request, token)
  for (const id of cleanupDatasets.splice(0)) await deleteDataset(request, token, id)
  await session.save(context)
})

/** Dataset z jednym sparsowanym plikiem. */
async function seedDataset(
  request: APIRequestContext,
  token: string,
  label: string,
): Promise<{ datasetId: string; documentId: string; name: string }> {
  const name = `E2E S27 ${label} ${uniq()}`
  const corpus = await seedCorpus(request, token, {
    datasetName: name,
    documentName: `e2e-s27-${label}.txt`,
    documentBody: DOC_BODY,
  })
  cleanupDatasets.push(corpus.datasetId)
  return { datasetId: corpus.datasetId, documentId: corpus.documentId, name }
}

/**
 * Dataset z metadanymi: plik dostaje `typ = raport` zwykłym PATCH (jak s25-metadata-filter) — dzięki
 * temu kreator filtra (czat, retrieval) widzi klucz `typ` i nie pokazuje „Bazy nie mają metadanych”.
 */
async function seedMetadataDataset(request: APIRequestContext, token: string): Promise<string> {
  const { datasetId, documentId } = await seedDataset(request, token, 'meta')
  await ok<unknown>(
    request.patch(`${API_URL}/api/v1/datasets/${datasetId}/documents/${documentId}`, {
      headers: { authorization: `Bearer ${token}` },
      data: { meta_fields: { typ: 'raport' } },
    }),
    'PATCH …/documents/{id} (meta_fields)',
  )
  return datasetId
}

async function expandAdvanced(page: Page): Promise<void> {
  const summary = page.getByRole('button', { name: 'Zaawansowane' })
  if ((await summary.getAttribute('aria-expanded')) === 'false') await summary.click()
}

/** Szuflada ustawień czatu: zakładka „Asystent”, rozwinięte „Zaawansowane”, sekcja filtra. */
async function openChatFilter(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  await expandAdvanced(page)
  await page.getByText(FILTER_SECTION, { exact: true }).click()
}

test.describe('SC-E67-06 krok 1: zdanie w dialogu zastosowania zmian', () => {
  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 390, height: 844 },
  ]) {
    test(`SC-E67-06 krok 1 (${viewport.width} px): dialog tłumaczy, że metadane powstają przy parsowaniu`, async ({
      page,
      request,
    }) => {
      const token = await adminToken(request)
      const { datasetId, name } = await seedDataset(request, token, 'k1')
      await page.setViewportSize(viewport)

      await page.goto(`/dataset/configuration/${datasetId}`)
      await expect(page.getByRole('heading', { name })).toBeVisible()
      await page.getByRole('button', { name: '+ Pole' }).click()
      await page.getByRole('group', { name: 'Pole 1' }).getByLabel('Klucz').fill('rok')
      await page.getByRole('switch', { name: 'Auto-metadane' }).click()
      await page.getByRole('button', { name: 'Zapisz' }).click()

      const dialog = page.getByRole('dialog', { name: APPLY_TITLE })
      await expect(dialog).toBeVisible()
      await expect(dialog).toContainText(APPLY_SENTENCE)
      await expectNoLayoutDefects(page, `dialog zastosowania zmian (${viewport.width} px)`)
    })
  }
})

test('SC-E67-06 krok 4: pusty „Wartość” w filtrze czatu → „Podaj wartość”, warunek nie jest zapisany', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const datasetId = await seedMetadataDataset(request, token)
  const chatId = await createChat(request, token, {
    name: `E2E S27 czat k4 ${uniq()}`,
    datasetIds: [datasetId],
  })
  const writes: string[] = []
  page.on('request', (req) => {
    if (/\/api\/v1\/chats\/[^/?]+$/.test(req.url()) && ['PATCH', 'PUT'].includes(req.method())) {
      writes.push(req.method())
    }
  })

  await page.goto(`/chat/${chatId}`)
  await openChatFilter(page)
  const modes = page.getByRole('radiogroup', { name: MODE_GROUP })
  await modes.getByRole('radio', { name: 'Ręczny' }).check()
  const condition = page.getByRole('group', { name: 'Warunek 1' })
  await condition.getByRole('combobox', { name: 'Klucz' }).click()
  await page.getByRole('option', { name: 'typ', exact: true }).click()
  // Wartość celowo zostaje pusta; operator domyślny wymaga wartości.
  await page.getByRole('button', { name: 'Zapisz' }).click()

  await expect(condition.getByText('Podaj wartość')).toBeVisible()
  await expect(condition.getByRole('combobox', { name: 'Wartość' })).toHaveAttribute(
    'aria-invalid',
    'true',
  )
  await expectNoLayoutDefects(page, 'błąd pustej wartości warunku (SC-06 krok 4)')
  // Szuflada zostaje otwarta, a do API nie poszedł żaden zapis czatu.
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeVisible()
  expect(writes, 'zapis czatu mimo pustej wartości warunku').toEqual([])
})

test('SC-E67-06 krok 5: klik w chip warunku nad polem pytania otwiera edycję filtra', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const datasetId = await seedMetadataDataset(request, token)
  const chatId = await createChat(request, token, {
    name: `E2E S27 czat k5 ${uniq()}`,
    datasetIds: [datasetId],
  })
  await ok<unknown>(
    request.patch(`${API_URL}/api/v1/chats/${chatId}`, {
      headers: { authorization: `Bearer ${token}` },
      data: {
        meta_data_filter: {
          method: 'manual',
          logic: 'and',
          manual: [{ key: 'typ', op: '=', value: 'raport' }],
        },
      },
    }),
    'PATCH /api/v1/chats/{id} (meta_data_filter)',
  )

  await page.goto(`/chat/${chatId}`)
  // Chip warunku (np. „typ = raport”) jest przyciskiem nad polem pytania — poza szufladą ustawień.
  const chip = page.getByRole('button', { name: /typ\s*=\s*raport/ })
  await expect(chip).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()
  await chip.click()

  // Klik otwiera ustawienia czatu przewinięte do sekcji filtra z zachowanym warunkiem.
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeVisible()
  const modes = page.getByRole('radiogroup', { name: MODE_GROUP })
  await expect(modes).toBeInViewport()
  await expect(modes.getByRole('radio', { name: 'Ręczny' })).toBeChecked()
  await expect(page.getByRole('group', { name: 'Warunek 1' })).toBeVisible()
  await expectNoLayoutDefects(page, 'edycja filtra otwarta z chipa (SC-06 krok 5)')
})

test('SC-E67-06 krok 6: wygaszone tryby w teście retrievalu mają wyjaśnienie', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const datasetId = await seedMetadataDataset(request, token)

  await openRetrievalTab(page, datasetId)
  await expandAdvanced(page)
  await page.getByText(FILTER_SECTION, { exact: true }).click()
  const modes = page.getByRole('radiogroup', { name: MODE_GROUP })
  for (const mode of ['Automatyczny', 'Półautomatyczny']) {
    await expect(modes.getByRole('radio', { name: mode, exact: true })).toBeDisabled()
    // Najechanie na podpis wygaszonego trybu pokazuje wyjaśnienie (tooltip na opakowaniu `span`).
    await modes.getByText(mode, { exact: true }).hover()
    await expect(
      page.getByText('dostępne w czacie — wymaga modelu czatu').first(),
      `wyjaśnienie przy wygaszonym trybie „${mode}”`,
    ).toBeVisible()
    await expectNoLayoutDefects(page, `tooltip przy trybie „${mode}” (SC-06 krok 6)`)
    await page.mouse.move(0, 0)
  }
})

test.describe('SC-E67-06 krok 7: podpowiedź trybu „Automatyczny” bez przewijania', () => {
  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 390, height: 844 },
  ]) {
    test(`SC-E67-06 krok 7 (${viewport.width} px): podpowiedź jest w oknie dialogu`, async ({
      page,
      request,
    }) => {
      const token = await adminToken(request)
      const datasetId = await seedMetadataDataset(request, token)
      const chatId = await createChat(request, token, {
        name: `E2E S27 czat k7 ${uniq()}`,
        datasetIds: [datasetId],
      })
      await page.setViewportSize(viewport)

      await page.goto(`/chat/${chatId}`)
      await openChatFilter(page)
      const modes: Locator = page.getByRole('radiogroup', { name: MODE_GROUP })
      await modes.getByRole('radio', { name: 'Automatyczny', exact: true }).check()

      const hint = page.getByText('Model sam ułoży filtr z pytania')
      await expect(hint).toBeVisible()
      // Bez przewijania użytkownika: podpowiedź w całości w widocznym obszarze (z uwzględnieniem
      // przewijalnej szuflady), a nie poniżej jej dolnej krawędzi.
      await expect(hint).toBeInViewport({ ratio: 1 })
      await expectNoLayoutDefects(page, `podpowiedź trybu „Automatyczny” (${viewport.width} px)`)
    })
  }
})

test('SC-E67-06 błąd zapisu pól metadanych: komunikat przy polu, nie alert karty', async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const name = `E2E S27 blad pol ${uniq()}`
  const datasetId = await createDataset(request, token, name)
  cleanupDatasets.push(datasetId)
  const message = 'Błąd testowy zapisu pól'
  // Wymuszony błąd PUT …/metadata/config (koperta RAGFlow: HTTP 200 + code ≠ 0).
  await page.route('**/api/v1/datasets/*/metadata/config', async (route) => {
    if (route.request().method() === 'PUT') {
      await route.fulfill({ json: { code: 102, message, data: null } })
    } else {
      await route.fallback()
    }
  })

  await page.goto(`/dataset/configuration/${datasetId}`)
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await page.getByRole('button', { name: '+ Pole' }).click()
  const row = page.getByRole('group', { name: 'Pole 1' })
  await row.getByLabel('Klucz').fill('rok')
  await page.getByRole('button', { name: 'Zapisz' }).click()

  // Komunikat leży przy polu (w wierszu „Pole 1”), a wpisana wartość zostaje.
  await expect(row.getByText(message)).toBeVisible()
  await expect(row.getByLabel('Klucz')).toHaveValue('rok')
  // Komunikat jest tylko przy polu — bez drugiego egzemplarza w alercie karty/sekcji.
  await expect(page.getByText(message)).toHaveCount(1)
  await expectNoLayoutDefects(page, 'błąd zapisu pól metadanych (SC-06)')
})
