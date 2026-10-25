// Scenariusz S16e (brief WP E5-H6e T2, kontrakt C2): wybór pierwszej bazy wiedzy przy pustym
// prompcie systemowym wypełnia pole „Prompt systemowy” domyślnym szablonem z `{knowledge}`
// (tekst backendu `DEFAULT_PROMPT_CONFIG["system"]`, K4) — bez tego walidacja blokowałaby zapis
// nowego czatu. Cała droga idzie przez prawdziwe UI (utworzenie czatu, szuflada ustawień),
// w dwóch szerokościach: 1280×800 i 390×844.
import { expect, test } from './fixtures'
import type { APIRequestContext, Page } from '@playwright/test'

import { apiLogin, loginViaUi, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'

const API_URL = process.env.WD_E2E_API_URL ?? ''
const DATASET_NAME = 'E2E S16e baza promptu'
const DOCUMENT_NAME = 'e2e-s16e-wawel.txt'
// Krótki tekst o Wawelu (> `min_chars` parsera) — baza musi mieć chunk, inaczej opcja wyboru
// byłaby wyszarzona, a `POST /chats` odrzuca puste bazy.
const DOCUMENT_BODY =
  'Zamek Królewski na Wawelu wznosi się na wzgórzu nad Wisłą w Krakowie i przez stulecia był ' +
  'siedzibą królów Polski. Najstarsze murowane budowle pochodzą z czasów Kazimierza Wielkiego.'
const CHAT_NAME = 'E2E S16e czat'
const VIEWPORT_WIDE = { width: 1280, height: 800 }
const VIEWPORT_NARROW = { width: 390, height: 844 }

/** Usuwa czaty i bazę scenariusza (HTTP 200 + `code 0`). */
async function cleanup(
  request: APIRequestContext,
  token: string,
  chatIds: string[],
  datasetId: string,
): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  await request.delete(`${API_URL}/api/v1/chats`, { headers, data: { ids: chatIds } })
  await request.delete(`${API_URL}/api/v1/datasets`, { headers, data: { ids: [datasetId] } })
}

/** Identyfikator czatu z adresu `/chat/:id` (po utworzeniu czatu przez UI). */
function chatIdFromUrl(page: Page): string {
  const id = new URL(page.url()).pathname.split('/').pop() ?? ''
  expect(id, `adres czatu: ${page.url()}`).not.toBe('')
  return id
}

/** Tworzy czat przez UI (lista → dialog nazwy) i zostawia stronę na `/chat/:id`. */
async function createChatViaUi(page: Page, name: string): Promise<string> {
  await page.goto('/chats')
  await expect(page).toHaveURL(/\/chats$/)
  await page.getByRole('button', { name: 'Utwórz czat' }).first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel(/Nazwa/).fill(name)
  await dialog.getByRole('button', { name: 'Utwórz' }).click()
  await expect(page).toHaveURL(/\/chat\/[^/]+$/)
  // Nazwa czatu nie jest nagłówkiem na każdej szerokości (przy 390 px widać tylko „Nowa
  // rozmowa”), więc gotowość ekranu potwierdza zębatka ustawień — i tak ją zaraz otwieramy.
  await expect(page.getByRole('button', { name: 'Ustawienia czatu' })).toBeVisible()
  return chatIdFromUrl(page)
}

/** Wybiera bazę w szufladzie ustawień i sprawdza wypełniony szablon promptu. */
async function assertPromptFilledAfterDatasetChoice(
  page: Page,
  datasetName: string,
): Promise<void> {
  await page.getByRole('button', { name: 'Ustawienia czatu' }).click()
  await page.getByRole('tab', { name: 'Asystent' }).click()
  await page.getByRole('combobox', { name: 'Bazy wiedzy' }).click()
  await page.getByRole('option', { name: datasetName }).click()

  await page.getByRole('tab', { name: 'Silnik promptu' }).click()
  const prompt = page.getByLabel(/Prompt systemowy/)
  await expect(prompt).toHaveValue(/^You are an assistant grounded in the dataset below/)
  await expect(prompt).toHaveValue(/\{knowledge\}/)
  // Szablon zawiera `{knowledge}`, więc walidacja nie zgłasza ostrzeżenia, a „Zapisz” jest aktywny.
  await expect(page.getByText(/musi zawierać \{knowledge\}/)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Zapisz' })).toBeEnabled()

  await page.getByRole('button', { name: 'Zapisz' }).click()
  await expect(page.getByRole('tab', { name: 'Asystent' })).toBeHidden()
  await expect(page.getByText('Zapisano ustawienia czatu.')).toBeVisible()
  // Koniec animacji zamykania szuflady przed końcem testu: strażnik układu (fixtures.ts) mierzy
  // ekran PO testach i w połowie slajdu wyjścia zobaczyłby paper poza oknem — to była usunięta
  // pozycja `layout-known-defects.ts` (R-UI-01 naprawiona w komponencie, tu tylko timing testu).
  await expect(
    page.locator('.MuiDrawer-paper').filter({ hasText: 'Ustawienia czatu' }),
  ).toBeHidden()
}

test('S16e: wybór bazy przy pustym prompcie wypełnia szablon z {knowledge} (desktop i 390)', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000)
  const token = await apiLogin(request)
  const corpus: SeededCorpus = await seedCorpus(request, token, {
    datasetName: DATASET_NAME,
    documentName: DOCUMENT_NAME,
    documentBody: DOCUMENT_BODY,
  })
  const chatIds: string[] = []

  try {
    await loginViaUi(page)

    // Desktop: świeży czat (baza nie wybrana), pierwsza baza ustawia prompt z `{knowledge}`.
    await page.setViewportSize(VIEWPORT_WIDE)
    chatIds.push(await createChatViaUi(page, `${CHAT_NAME} desktop`))
    await assertPromptFilledAfterDatasetChoice(page, DATASET_NAME)

    // 390×844: ta sama droga na pełnoszerokościowej szufladzie — świeży czat, ten sam efekt.
    await page.setViewportSize(VIEWPORT_NARROW)
    chatIds.push(await createChatViaUi(page, `${CHAT_NAME} 390`))
    await assertPromptFilledAfterDatasetChoice(page, DATASET_NAME)
  } finally {
    await cleanup(request, token, chatIds, corpus.datasetId)
  }
})
