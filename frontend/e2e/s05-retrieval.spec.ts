// Scenariusz S6-05 (08 §11.2, kontrakt WP E3-H2a §K4): test retrievalu — pytanie o znany fragment
// dokumentu zwraca kartę wyniku z nazwą dokumentu i chipem procentowym, podniesienie progu
// podobieństwa do 0.99 daje pusty stan „Nie znaleziono…”, a wybór języka międzyjęzykowego posyła
// `cross_languages` w ciele żądania. Wsiew idzie przez API (`seedCorpus`), UI sprawdza zakładkę
// datasetu; brak mocków — te same trasy woła aplikacja.
import type { APIRequestContext } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, loginViaUi, seedCorpus } from './helpers'
import { expectNoSeriousA11y } from './helpers/axe'
import { askQuestion, openRetrievalTab, setThreshold } from './helpers/retrieval'

const DATASET_NAME = 'E2E S6-05 baza'
const DOCUMENT_NAME = 'e2e-s05-smok.txt'
const DOCUMENT_BODY =
  'Wawelski smok pilnował zbocza Wawelu, a szewc Skuba podsunął mu baranka z siarką.'
const QUESTION = 'szewc Skuba baranka z siarką'
const HIGH_THRESHOLD = 0.99
/** Limit oczekiwania na wynik: `POST /api/v1/retrieval` liczy się dłużej niż domyślne 5 s Playwrighta. */
const RESULT_TIMEOUT_MS = 45_000

/** Wsiew: baza wiedzy z jednym sparsowanym dokumentem tekstowym (jak S6-06). */
async function seeded(request: APIRequestContext): Promise<string> {
  const token = await apiLogin(request)
  const corpus = await seedCorpus(request, token, {
    datasetName: DATASET_NAME,
    documentName: DOCUMENT_NAME,
    documentBody: DOCUMENT_BODY,
  })
  return corpus.datasetId
}

test('S6-05: trafienie dosłownym fragmentem i pusty stan przy progu 0.99', async ({
  page,
  request,
}) => {
  // Wsiew parsuje dokument (odpytywanie workera) — jak w S6-06/S6-07.
  test.setTimeout(240_000)
  await resetDb(request)
  const datasetId = await seeded(request)

  await loginViaUi(page)
  await openRetrievalTab(page, datasetId)

  // a) Przed uruchomieniem nie ma żadnego wyniku — widać zachętę.
  await expect(page.getByText(/Nie uruchomiono jeszcze testu/)).toBeVisible()

  // b) Pytanie dosłownym fragmentem dokumentu trafia w chunk (trafienie pełnotekstowe).
  await askQuestion(page, QUESTION)
  const results = page.getByTestId('retrieval-result')
  await expect(results.first()).toBeVisible({ timeout: RESULT_TIMEOUT_MS })
  expect(await results.count(), 'liczba kart wyników').toBeGreaterThanOrEqual(1)
  await expect(results.first()).toContainText(DOCUMENT_NAME)
  await expect(page.getByTestId('retrieval-chip-hybrid').first()).toContainText(/\d+(\.\d)?%/)
  await expect(page.getByTestId('retrieval-total')).not.toBeEmpty()

  // Główny ekran scenariusza: zakładka retrievalu z kartami wyników (jasny motyw).
  await expectNoSeriousA11y(page, 'S6-05 wyniki retrievalu')

  // c) Próg 0.99 odsiewa wszystko — pusty stan bez kart wyników.
  await setThreshold(page, HIGH_THRESHOLD)
  await page.getByTestId('retrieval-run').click()
  await expect(page.getByTestId('retrieval-empty')).toBeVisible({ timeout: RESULT_TIMEOUT_MS })
  await expect(page.getByTestId('retrieval-empty')).toContainText(/^Nie znaleziono/)
  await expect(results).toHaveCount(0)

  // d) Wybór języka międzyjęzykowego trafia do ciała żądania jako `cross_languages` (K4).
  //
  // Ciało czytamy z żądania przechwyconego trasą — nie z `page.waitForRequest`. Middleware
  // klienta API klonuje `Request` (`request.clone()`, by móc powtórzyć żądanie po 401), a ciało
  // sklonowanego żądania Chromium wysyła strumieniem: DevTools nie podaje wtedy ani `postData`,
  // ani `postDataEntries`, więc `request.postDataJSON()` zwraca `null` także dla żądań, które
  // backend obsłużył poprawnie (diagnoza t8-fix-s05). Trasa (`route.continue()` — to nie mock,
  // żądanie idzie do backendu) wymusza zbuforowanie ciała po stronie przeglądarki.
  // Nasłuch przed kliknięciem „Uruchom”, inaczej żądanie mogłoby umknąć.
  await page.getByText('Zaawansowane').click()
  await page.getByRole('combobox', { name: 'Wyszukiwanie międzyjęzykowe' }).click()
  await page.getByRole('option', { name: 'Niemiecki' }).click()
  // `Promise` zamiast zmiennej: TypeScript zwęża typ zmiennej przypisywanej w domknięciu do
  // `null`. Rozwiązanie następuje przy przechwyceniu żądania, więc `await` dowodzi, że żądanie
  // poszło — i niesie ciało.
  const postedBody = new Promise<{ cross_languages?: string[] } | null>((resolve) => {
    void page.route('**/api/v1/retrieval', async (route) => {
      resolve(route.request().postDataJSON() as { cross_languages?: string[] } | null)
      await route.continue()
    })
  })
  await page.getByTestId('retrieval-run').click()
  expect((await postedBody)?.cross_languages).toEqual(['German'])
})

// D-maj1 QA E3-H4: pole „Pytanie” ma `multiline` + `shrink`, a motyw nadawał mu stałą wysokość
// (`MuiOutlinedInput` size medium → 2.5rem). `InputBase` centruje zawartość, więc tekstarea
// wychodziła ponad obramowanie i zwinięta etykieta nachodziła na pierwszą linię tekstu (w obu
// motywach). Tu mierzymy realną geometrię po wpisaniu tekstu — jsdom tego nie policzy.
test('S6-05 (D-maj1): etykieta „Pytanie” leży nad polem, nie na wpisanym tekście', async ({
  page,
  request,
}) => {
  test.setTimeout(240_000)
  await resetDb(request)
  const datasetId = await seeded(request)

  // Zrzuty QA (d09b, l09b) pokazują defekt w obu motywach; sprawdzamy ciemny.
  await page.emulateMedia({ colorScheme: 'dark' })
  await loginViaUi(page)
  await openRetrievalTab(page, datasetId)

  const question = page.getByTestId('retrieval-question')
  await question.fill(QUESTION)
  const label = page.locator('.MuiFormControl-root:has([data-testid="retrieval-question"]) label')
  await expect(label).toHaveAttribute('data-shrink', 'true')

  const labelBox = await label.boundingBox()
  const inputBox = await question.boundingBox()
  if (!labelBox || !inputBox) throw new Error('brak geometrii pola pytania')
  // Zwinięta etykieta siedzi na krawędzi obramowania: jej środek jest nad górną krawędzią pola.
  expect(
    labelBox.y + labelBox.height / 2,
    'środek etykiety nad górną krawędzią pola tekstowego',
  ).toBeLessThanOrEqual(inputBox.y + 2)
})
