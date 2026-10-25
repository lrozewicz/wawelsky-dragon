// Scenariusz S6-08 (08 §11.2, kontrakt WP E3-5b §„e2e (T7)"): sesje czatu — pierwsze pytanie
// tworzy rozmowę o nazwie z pierwszych 50 znaków pytania, menu pozwala zmienić nazwę i usunąć
// rozmowę, a przeładowanie adresu z `?conversationId=` odtwarza historię z cytowaniem.
// Czat i baza wiedzy powstają przez API (kontrakt §T7); UI sprawdza zachowanie sesji.
import type { APIRequestContext, Page } from '@playwright/test'

import { ADMIN_EMAIL, ADMIN_PASSWORD, expect, test } from './fixtures'
import { expectNoSeriousA11y } from './helpers/axe'
import { apiLogin, createChat, deleteAllChats, seedCorpus } from './helpers'
import type { SeededCorpus } from './helpers'

const DATASET_NAME = 'E2E S6-08 baza'
const DOCUMENT_NAME = 'e2e-s08-smok.txt'
const DOCUMENT_BODY = [
  'Wawelski smok mieszkał w jamie pod Wawelem.',
  '',
  'Legenda o smoku wawelskim: smok pilnował zbocza Wawelu, a zguba miasta miała',
  'na imię Zygfryd. Smok wawelski został pokonany przez szewca Skubę, który',
  'podrzucił mu barana wypełnionego siarką.',
  '',
].join('\n')
// Pierwsze pytanie jest dłuższe niż 50 znaków — nazwa rozmowy to jego pierwsze 50 znaków.
const QUESTION = 'Gdzie mieszkał smok wawelski i kto według legendy go pokonał?'
const RENAMED = 'E2E rozmowa o smoku'

type Shared = { token: string; corpus: SeededCorpus; chatId: string }

let shared: Promise<Shared> | undefined

function seeded(request: APIRequestContext): Promise<Shared> {
  shared ??= (async () => {
    const token = await apiLogin(request)
    const corpus = await seedCorpus(request, token, {
      datasetName: DATASET_NAME,
      documentName: DOCUMENT_NAME,
      documentBody: DOCUMENT_BODY,
    })
    const chatId = await createChat(request, token, {
      name: 'E2E S6-08 czat',
      datasetIds: [corpus.datasetId],
    })
    return { token, corpus, chatId }
  })()
  return shared
}

// Czat zostawiony w bazie sprzątamy po pliku — kolejne scenariusze startują z czystą listą.
test.afterAll(async ({ request }) => {
  const current = shared === undefined ? undefined : await shared
  if (current !== undefined) await deleteAllChats(request, current.token)
})

/** Logowanie kontem z seedu K9 przez UI (jak S6-01 i S7a). */
async function loginViaUi(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByTestId('login-email').fill(ADMIN_EMAIL)
  await page.getByTestId('login-password').fill(ADMIN_PASSWORD)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('home-banner')).toBeVisible()
}

test('S6-08: nazwa z pytania, zmiana nazwy, historia z cytowaniem i usunięcie', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000)
  const { chatId } = await seeded(request)

  await loginViaUi(page)
  await page.goto(`/chat/${chatId}`)
  const panel = page.getByTestId('sessions-panel')
  await expect(panel.getByText('Brak rozmów')).toBeVisible()

  // 1. Pierwsze pytanie tworzy rozmowę (sesja po stronie backendu) i wpisuje jej id do adresu.
  await page.getByPlaceholder('Wpisz pytanie…').fill(QUESTION)
  await page.getByRole('button', { name: 'Wyślij' }).click()
  await expect(page.getByTestId('message-assistant').last()).toContainText('Na podstawie źródeł', {
    timeout: 30_000,
  })
  await expect(page).toHaveURL(/conversationId=/)

  const sessionName = QUESTION.slice(0, 50)
  await expect(panel.getByText(sessionName, { exact: true })).toBeVisible()

  // 2. Zmiana nazwy z menu rozmowy.
  await panel.getByRole('button', { name: `Menu rozmowy ${sessionName}` }).click()
  await page.getByRole('menuitem', { name: 'Zmień nazwę' }).click()
  const renameDialog = page.getByRole('dialog')
  await renameDialog.getByLabel('Nazwa').fill(RENAMED)
  await renameDialog.getByRole('button', { name: 'Zapisz' }).click()
  await expect(panel.getByText(RENAMED, { exact: true })).toBeVisible()

  // 3. Przeładowanie adresu z `?conversationId=` odtwarza historię: pytanie, odpowiedź
  //    i chip cytowania otwierający MODAL (nazwa dokumentu, podobieństwo) — kontrakt WP E5-H3
  //    §Decyzje UX #7 (DEC-243).
  await page.reload()
  await expect(panel.getByText(RENAMED, { exact: true })).toBeVisible()
  await expect(page.getByText(QUESTION)).toBeVisible()
  const chip = page.getByRole('button', { name: 'Cytowanie 1' })
  await expect(chip).toBeVisible()

  // Jasny motyw, główny ekran scenariusza: czat z odtworzoną historią i panelem rozmów.
  // Modal cytowania jest modalny, więc sprawdzamy przed jego otwarciem.
  await expectNoSeriousA11y(page, 'S6-08 czat z historią rozmowy')

  // Klik na chipie otwiera modal (hover nic nie otwiera). Modal cytowania rozpoznajemy po
  // zawartości (`cite-content`), jak w s07 — szuflada podglądu dokumentu też ma `role="dialog"`.
  await chip.click()
  const citeDialog = page.getByRole('dialog').filter({ has: page.getByTestId('cite-content') })
  await expect(citeDialog).toBeVisible()
  await expect(citeDialog).toContainText(DOCUMENT_NAME)
  await expect(citeDialog).toContainText(/Podobieństwo: \d+%/)

  // Modal jest modalny: MUI ukrywa resztę strony przed czytnikiem ekranu i zasłania ją
  // przezroczystym backdropem, więc zamykamy go Esc (z fokusem wracającym na chip), zanim
  // dotkniemy czegokolwiek innego — inaczej `getByRole('dialog')` przy usuwaniu rozmowy byłby
  // niejednoznaczny.
  await page.keyboard.press('Escape')
  await expect(citeDialog).toBeHidden()
  await expect(chip).toBeFocused()

  // 4. Usunięcie rozmowy z potwierdzeniem — panel wraca do pustego stanu.
  await panel.getByRole('button', { name: `Menu rozmowy ${RENAMED}` }).click()
  await page.getByRole('menuitem', { name: 'Usuń' }).click()
  const confirmDialog = page.getByRole('dialog')
  await expect(confirmDialog).toContainText(`Czy usunąć rozmowę „${RENAMED}”?`)
  await confirmDialog.getByRole('button', { name: 'Usuń' }).click()
  await expect(panel.getByText('Brak rozmów')).toBeVisible()
})
