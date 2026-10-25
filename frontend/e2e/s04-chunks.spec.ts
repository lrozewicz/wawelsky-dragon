// Scenariusz S6-04 (08 §11.2, kontrakt WP E3-H2a §K3): strona chunków dokumentu.
// Klik w nazwę dokumentu na liście plików prowadzi na `/chunk/parsed/chunks`, filtr
// Włączone/Wyłączone jedzie na serwer jako parametr `available` listy, a wyłączenie chunku
// i dodanie słowa kluczowego w dialogu utrwalają się po przeładowaniu (potwierdza to też API).
// Baza i dokument powstają przez API (`seedChunkedDocument` kontroluje `chunk_count >= 2`).
import type { Locator, Request } from '@playwright/test'

import { expect, resetDb, test } from './fixtures'
import { apiLogin, loginViaUi } from './helpers'
import { expectNoSeriousA11y } from './helpers/axe'
import { listChunks, seedChunkedDocument } from './helpers/chunks'

const DATASET_NAME = 'E2E S6-04 baza'
const DOCUMENT_NAME = 'e2e-s04-chunks.txt'
/** Słowo kluczowe dopisane do drugiego chunku w dialogu edycji. */
const KEYWORD = 'e2e-klucz'
/** Karty chunków mają testid `chunk-card-<id>` (kontrakt §data-testid). */
const CARD = '[data-testid^="chunk-card-"]'

// Dokument na tyle długi i wieloakapitowy, by parser (próg 512 tokenów, podział po `\n`)
// wydał co najmniej dwa chunki — pilnuje tego `seedChunkedDocument(minChunks: 2)`.
const DOCUMENT_BODY = [
  'Zamek Królewski na Wawelu wznosi się na wapiennym wzgórzu nad Wisłą w Krakowie i od stuleci góruje nad miastem jako dawna siedziba królów Polski. Wzgórze było zamieszkane już w paleolicie, a ślady osadnictwa odkryto między innymi w jaskini zwanej Smoczą Jamą.',
  'Pierwsze murowane budowle powstawały na Wawelu za panowania Kazimierza Wielkiego w XIV wieku. Gotycki zamek z wieżą Łokietkową oraz okazała katedra tworzyły wówczas reprezentacyjny zespół rezydencjonalny, porównywany z najznaczniejszymi dworami Europy.',
  'Za panowania Władysława Jagiełły i jego następców zamek rozbudowywano, a w XV wieku dołączono między innymi Salę Poselską i kaplice, w których odprawiano nabożeństwa dworskie. Każda z tych komnat miała własne przeznaczenie i wystrój.',
  'Renesansową przebudowę prowadzono na polecenie Zygmunta Starego i jego żony Bony. Włoscy architekci, wśród nich Bartolomeo Berrecci, nadali dziedzińcowi arkadową formę z kolumnami i loggiami, którą uznaje się za jedno z najpiękniejszych rozwiązań tego typu na północ od Alp.',
  'W komnatach zamku można oglądać arrasy wawelskie, tkaniny utkane w Brukseli na zamówienie Zygmunta Augusta. Cykl liczył pierwotnie ponad sto pięćdziesiąt sztuk, a te zachowane przedstawiają sceny biblijne, krajobrazy oraz godła Rzeczypospolitej.',
  'Kolekcja porcelany wawelskiej obejmuje wyroby z Miśni, Sèvres, Wiednia i Chin, a najstarsze z nich sięgają XVIII wieku. Wśród eksponatów wyróżniają się serwisy używane na dworze Stanisława Augusta Poniatowskiego.',
  'Szczerbiec, miecz koronacyjny królów Polski, jest jednym z najcenniejszych zabytków na Wawelu. Ostrze towarzyszyło ceremonii koronacyjnej od czasów Władysława Jagiełły, choć samo wykuto prawdopodobnie w XII albo XIII wieku.',
  'Wzgórze wawelskie obejmuje także katedrę świętych Stanisława i Wacława, w której spoczywają królowie, biskupi i wodzowie. Pod posadzką i w kaplicach znajdują się krypty z sarkofagami, a wejście do nich prowadzi ze starego przedsionka.',
  'Katedra była miejscem koronacji prawie wszystkich władców Polski. Pierwsza konsekracja świątyni nastąpiła w 1364 roku za panowania Kazimierza Wielkiego, a kolejne przebudowy nadały jej obecny, trójnawowy kształt z ambitem i wieńcem kaplic.',
  'Wieża Zygmunta wznosi się obok katedry i mieści dzwon Zygmunt odlany w 1521 roku przez ludwisarza Hansa Behema. Dzwon waży blisko jedenaście ton i bije tylko przy największych okazjach państwowych oraz kościelnych.',
  'Smocza Jama to wapienna jaskinia u stóp wzgórza, związana z legendą o smoku wawelskim. Według opowieści bestia pustoszyła okoliczne osady, dopóki nie poradził sobie z nią szewczyk Skuba, który podrzucił zwierzęciu barana wypełnionego siarką.',
  'Legenda o smoku wawelskim pojawiła się w najstarszych kronikach, między innymi u Wincentego Kadłubka. Historycy traktują ją jako opowieść symboliczną, w której smok oznacza wrogie siły zagrażające młodemu państwu.',
  'Wawel był świadkiem wielu wydarzeń politycznych. Tutaj obradowano nad unią z Litwą, tutaj podejmowano decyzje o wojnach i traktatach, a także tutaj przechowywano skarbiec koronny oraz archiwum królestwa.',
  'Po rozbiorach zamek służył wojskom austriackim jako koszary i szpital. W tym okresie wnętrza podzielono na mniejsze pomieszczenia, a część wyposażenia wywieziono; dopiero na początku XX wieku rozpoczęto prace konserwatorskie.',
  'W okresie międzywojennym Wawel stał się siedzibą prezydentów Rzeczypospolitej, a zamek odzyskał funkcję reprezentacyjną. Odrestaurowano wówczas dziedziniec, komnaty oraz dachy, przywracając budowli dawny wygląd.',
  'W czasie drugiej wojny światowej zamek był siedzibą władz okupacyjnych, a zbiory narażono na grabież i zniszczenie. Część najcenniejszych zabytków ewakuowano wcześniej, między innymi przez Rumunię i Francję.',
  'Po wojnie zamek i katedra stały się muzeum oraz miejscem uroczystości państwowych. Zbiory wawelskie obejmują dziś malarstwo, rzeźbę, tkaniny, złotnictwo oraz pamiątki historyczne gromadzone przez kolejne pokolenia.',
  'Zamek udostępnia zwiedzającym kilka tras. Trasa reprezentacyjna prowadzi przez Salę Poselską i Salę Senatorską, trasa prywatna obejmuje komnaty królewskie, a osobne bilety obowiązują do skarbca koronnego oraz do zbrojowni.',
  'W Sali Senatorskiej zachowały się kasetony z głowami postaci, a w Sali Poselskiej podziwiać można strop oraz fryz z motywami roślinnymi. Nazwy komnat odnoszą się do funkcji, jakie pełniły w czasach monarchii.',
  'Dziedziniec arkadowy otaczają trzy kondygnacje krużganków, podpartych kolumnami o różnych kapitelach. Na parterze i pierwszym piętrze zachowano kamienne obramienia, a w narożnikach umieszczono latarnie i figury.',
  'Podziemia zamku kryją ślady starszych budowli, między innymi romańskich murów i gotyckich piwnic. Badania archeologiczne prowadzone na wzgórzu dostarczyły tysięcy zabytków, od narzędzi po monety i wyroby rzemieślnicze.',
  'Ogród zamkowy, odtworzony w XX wieku, nawiązuje do renesansowych założeń. Roślinność dobrano tak, by przypominała odmiany uprawiane w czasach Zygmunta Starego, a wzdłuż ścieżek ustawiono ławy i altany.',
  'Wawel pozostaje symbolem polskiej państwowości. W krypcie katedralnej spoczywają między innymi Józef Piłsudski, Władysław Sikorski oraz Lech Kaczyński, a pod wieżą srebrnych dzwonów znajdują się groby królewskie.',
  'Zwiedzanie wzgórza warto zaplanować na kilka godzin, ponieważ zamek, katedra i wystawy mieszczą się w osobnych budynkach. Wejście na dziedziniec jest bezpłatne, a bilety do komnat najlepiej kupić z wyprzedzeniem.',
].join('\n')

/** Identyfikator chunku z karty (`data-testid` = `chunk-card-<id>`). */
async function cardId(card: Locator): Promise<string> {
  const testId = (await card.getAttribute('data-testid')) ?? ''
  return testId.replace('chunk-card-', '')
}

// Predykat żądania listy chunków z danym `available` (filtr serwerowy — E3-H2a §K3). Seed daje
// kilka chunków (jedna strona), więc zamiast liczby stron pilnujemy parametru w adresie.
function listRequestWith(available: string): (request: Request) => boolean {
  return (request) => {
    if (request.method() !== 'GET' || !request.url().includes('/chunks')) return false
    return new URL(request.url()).searchParams.get('available') === available
  }
}

test('S6-04: strona chunków — filtr, wyłączenie i edycja chunku utrwalone po przeładowaniu', async ({
  page,
  request,
}) => {
  // Seed czeka na `run = DONE` (do 90 s) plus narzut UI i dwóch odświeżeń listy.
  test.setTimeout(180_000)

  await resetDb(request)
  const token = await apiLogin(request)
  const corpus = await seedChunkedDocument(request, token, {
    datasetName: DATASET_NAME,
    documentName: DOCUMENT_NAME,
    documentBody: DOCUMENT_BODY,
  })

  await loginViaUi(page)

  // (a) Klik w nazwę dokumentu na liście plików otwiera stronę chunków.
  await page.goto(`/dataset/files/${corpus.datasetId}`)
  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible({ timeout: 15_000 })
  await page.getByRole('link', { name: DOCUMENT_NAME }).click()
  await expect(page).toHaveURL(
    new RegExp(`/chunk/parsed/chunks\\?id=${corpus.datasetId}&doc_id=${corpus.documentId}`),
  )
  const chunksPage = page.getByTestId('chunks-page')
  await expect(chunksPage).toBeVisible({ timeout: 15_000 })
  // Breadcrumbs strony chunków (bazy wiedzy → pliki datasetu → dokument); te same etykiety ma
  // pasek szczegółów datasetu, dlatego szukamy w obrębie `chunks-page` (kontrakt §1a).
  await expect(chunksPage.getByRole('navigation', { name: 'Ścieżka nawigacji' })).toContainText(
    DOCUMENT_NAME,
  )

  const cards = page.locator(CARD)
  await expect(cards.first()).toBeVisible({ timeout: 15_000 })
  const total = await cards.count()
  expect(total, 'liczba kart chunków').toBeGreaterThanOrEqual(2)
  const firstId = await cardId(cards.nth(0))
  const secondId = await cardId(cards.nth(1))

  // Główny ekran scenariusza: strona chunków z listą kart (jasny motyw).
  await expectNoSeriousA11y(page, 'S6-04 chunki')

  // (b) Wyłączenie pierwszego chunku przełącznikiem i filtr dostępności serwerowy: żądanie listy
  //     niesie parametr `available` (E3-H2a §K3).
  await page.getByTestId(`chunk-switch-${firstId}`).click()
  await expect(page.getByTestId(`chunk-switch-${firstId}`).locator('input')).not.toBeChecked()

  const disabledRequest = page.waitForRequest(listRequestWith('false'))
  await page.getByTestId('chunks-filter-disabled').click()
  await disabledRequest
  await expect(cards).toHaveCount(1)
  await expect(cards.nth(0)).toHaveAttribute('data-testid', `chunk-card-${firstId}`)

  const enabledRequest = page.waitForRequest(listRequestWith('true'))
  await page.getByTestId('chunks-filter-enabled').click()
  await enabledRequest
  await expect(cards).toHaveCount(total - 1)

  // „Wszystkie” wraca do pełnej listy (żądanie bez parametru `available`).
  await page.getByTestId('chunks-filter-all').click()
  await expect(cards).toHaveCount(total)

  // (c) Edycja drugiego chunku — dodanie słowa kluczowego w dialogu (Autocomplete freeSolo:
  //     tekst wpisany w pole staje się chipem po Enter).
  await page.getByTestId(`chunk-edit-${secondId}`).click()
  const dialog = page.getByTestId('chunk-dialog')
  await expect(dialog).toBeVisible()
  const keywords = dialog.getByTestId('chunk-dialog-keywords').locator('input')
  await keywords.fill(KEYWORD)
  await keywords.press('Enter')
  await dialog.getByTestId('chunk-dialog-save').click()
  await expect(dialog).toBeHidden()
  await expect(cards.nth(1).getByText(KEYWORD)).toBeVisible({ timeout: 15_000 })

  // (d) Po przeładowaniu oba stany wracają z backendu: pierwszy chunk wyłączony, drugi z chipem.
  await page.reload()
  await expect(chunksPage).toBeVisible({ timeout: 15_000 })
  await expect(cards).toHaveCount(total, { timeout: 15_000 })
  await expect(cards.nth(1).getByText(KEYWORD)).toBeVisible({ timeout: 15_000 })
  await page.getByTestId('chunks-filter-disabled').click()
  await expect(cards).toHaveCount(1)
  await expect(cards.nth(0)).toHaveAttribute('data-testid', `chunk-card-${firstId}`)

  // (e) To samo przez API — kolejność listy pokrywa się z kolejnością kart.
  const listed = await listChunks(request, token, corpus.datasetId, corpus.documentId)
  expect(listed.map((chunk) => chunk.id).slice(0, 2)).toEqual([firstId, secondId])
  expect(listed[0]?.available).toBe(false)
  expect(listed[1]?.important_keywords).toContain(KEYWORD)
})
