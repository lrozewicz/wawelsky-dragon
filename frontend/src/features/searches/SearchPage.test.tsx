import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  apiUrl,
  fixtureRetrievalChunk,
  resetSearchesFixtures,
  retrievalHandlers,
  searchFixtureApp,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'
import type { Language } from '../../i18n'

import { SearchPage } from './SearchPage'

afterEach(cleanup)
beforeEach(resetSearchesFixtures)

// Napisy z `locales/pl/searches.json` — interfejs polski jest domyślny w `renderWithProviders`.
const SEARCH_ID = 'search-1'
const SEARCH_NAME = 'Wyszukiwarka testowa'
const WELCOME = 'Cześć User! O co chcesz zapytać?'
const PLACEHOLDER = 'Zadaj pytanie…'
const BAR_LABEL = 'Pytanie'
const PAGE_SIZE_LABEL = 'Wyników na stronę'
const TOTAL = 'Znaleziono 2 wyniki'
const HITS_ERROR = 'Nie udało się pobrać wyników.'
const SETTINGS_OPEN = 'Otwórz ustawienia wyszukiwarki'
const SETTINGS_TITLE = 'Ustawienia wyszukiwarki'
const SUMMARY_TEXT = /Odpowiedź na podstawie źródeł/

/** Dwa trafienia z różnych dokumentów — nazwa dokumentu otwiera podgląd. */
function smokeChunks() {
  return [
    fixtureRetrievalChunk({
      id: 'c1',
      document_id: 'doc-1',
      document_keyword: 'Smok.pdf',
      similarity: 0.9,
    }),
    fixtureRetrievalChunk({
      id: 'c2',
      document_id: 'doc-2',
      document_keyword: 'Legenda.txt',
      similarity: 0.8,
    }),
  ]
}

/** MSW trafień + rejestr ciał żądań `POST /api/v1/retrieval`. */
function useSmokeApi(chunks = smokeChunks()) {
  const retrieval: Record<string, unknown>[] = []
  server.use(...retrievalHandlers({ chunks, onRequest: (body) => retrieval.push(body) }))
  return { retrieval }
}

/**
 * Render strony i czekanie na wczytaną wyszukiwarkę (nazwa trafia do nagłówka kontenera).
 * Zapytanie po tekście, nie po roli: otwarta szuflada (MUI `Modal`) oznacza resztę drzewa
 * jako `aria-hidden`, więc zapytania ról przestałyby widzieć nagłówek.
 */
async function renderPage(language: Language = 'pl'): Promise<void> {
  await renderWithProviders(<SearchPage searchId={SEARCH_ID} />, { language })
  await screen.findByText(SEARCH_NAME)
}

/** Wpisuje pytanie w pasku i wysyła Enterem (etykieta paska zależy od języka interfejsu). */
async function ask(
  user: ReturnType<typeof userEvent.setup>,
  text: string,
  barLabel: string = BAR_LABEL,
): Promise<void> {
  await user.type(screen.getByLabelText(barLabel), text)
  await user.keyboard('{Enter}')
}

// Odmiana licznika trafień wg reguł liczby mnogiej (kontrakt WP E4-H1 §T4): PL 0 i 5 → „wyników”,
// 1 → „wynik”, 2 i 22 → „wyniki”; EN 1 → „result”, 2 → „results”.
// Wzorce zakotwiczone — `toHaveTextContent` ze zwykłym napisem dopuszcza podciągi,
// a „Znaleziono 1 wynik” jest podciągiem błędnego „Znaleziono 1 wyników”.
const PLURAL_CASES: [Language, number, string, RegExp][] = [
  ['pl', 0, BAR_LABEL, /^Znaleziono 0 wyników$/],
  ['pl', 1, BAR_LABEL, /^Znaleziono 1 wynik$/],
  ['pl', 2, BAR_LABEL, /^Znaleziono 2 wyniki$/],
  ['pl', 5, BAR_LABEL, /^Znaleziono 5 wyników$/],
  ['pl', 22, BAR_LABEL, /^Znaleziono 22 wyniki$/],
  ['en', 1, 'Question', /^Found 1 result$/],
  ['en', 2, 'Question', /^Found 2 results$/],
]

describe('SearchPage', () => {
  it('ekran startowy wita nickiem i pokazuje duży pasek', async () => {
    useSmokeApi()
    await renderPage()

    expect(screen.getByText(WELCOME)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(PLACEHOLDER)).toBeInTheDocument()
  })

  it('wysłanie pytania uruchamia podsumowanie, trafienia i chipy powiązanych', async () => {
    const { retrieval } = useSmokeApi()
    await renderPage()
    const user = userEvent.setup()

    await ask(user, 'smok')

    expect(await screen.findByText(SUMMARY_TEXT)).toBeInTheDocument()
    expect(await screen.findByTestId('related-chips')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Powiązane pytanie 1' })).toBeInTheDocument()

    const hits = await screen.findByTestId('search-hits')
    expect(within(hits).getAllByTestId('search-hit')).toHaveLength(2)
    expect(screen.getByTestId('search-total')).toHaveTextContent(TOTAL)

    await waitFor(() => expect(retrieval).toHaveLength(1))
    expect(retrieval[0]).toMatchObject({
      question: 'smok',
      page: 1,
      page_size: 10,
      dataset_ids: ['ds-1'],
    })
  })

  it.each(PLURAL_CASES)(
    'odmienia licznik trafień (%s) dla %i wyników',
    async (language, count, barLabel, expected) => {
      useSmokeApi(
        Array.from({ length: count }, (_, index) =>
          fixtureRetrievalChunk({ id: `c${index + 1}`, similarity: 0.9 }),
        ),
      )
      await renderPage(language)

      await ask(userEvent.setup(), 'smok', barLabel)

      expect(await screen.findByTestId('search-total')).toHaveTextContent(expected)
    },
  )

  it('klik nazwy dokumentu otwiera szufladę podglądu', async () => {
    useSmokeApi()
    server.use(
      http.get(
        apiUrl('/api/v1/documents/:documentId/preview'),
        () =>
          new HttpResponse('Smok wawelski.', {
            headers: { 'Content-Type': 'text/plain; charset=utf-8' },
          }),
      ),
    )
    await renderPage()
    const user = userEvent.setup()
    await ask(user, 'smok')

    await user.click(await screen.findByRole('button', { name: 'Otwórz dokument Smok.pdf' }))

    expect(await screen.findByRole('heading', { name: 'Smok.pdf' })).toBeInTheDocument()
  })

  it('klik chipu pokrewnego ponawia zapytanie i pasek pokazuje nowe pytanie', async () => {
    const { retrieval } = useSmokeApi()
    await renderPage()
    const user = userEvent.setup()
    await ask(user, 'smok')
    await waitFor(() => expect(retrieval).toHaveLength(1))

    await user.click(await screen.findByRole('button', { name: 'Powiązane pytanie 2' }))

    await waitFor(() => expect(retrieval).toHaveLength(2))
    expect(retrieval[1]).toMatchObject({ question: 'Powiązane pytanie 2', page: 1 })
    await waitFor(() => expect(screen.getByLabelText(BAR_LABEL)).toHaveValue('Powiązane pytanie 2'))
  })

  it('brak baz wiedzy otwiera szufladę ustawień samoczynnie', async () => {
    useSmokeApi()
    server.use(
      http.get(apiUrl('/api/v1/searches/:searchId'), () =>
        HttpResponse.json({
          code: 0,
          message: '',
          data: {
            ...searchFixtureApp,
            search_config: { ...searchFixtureApp.search_config, kb_ids: [] },
          },
        }),
      ),
    )
    await renderPage()

    expect(await screen.findByText(SETTINGS_TITLE)).toBeInTheDocument()
  })

  it('zębatka otwiera i zamyka szufladę ustawień', async () => {
    useSmokeApi()
    await renderPage()
    const user = userEvent.setup()

    expect(screen.queryByText(SETTINGS_TITLE)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: SETTINGS_OPEN }))
    expect(await screen.findByText(SETTINGS_TITLE)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Zamknij ustawienia' }))
    await waitFor(() => expect(screen.queryByText(SETTINGS_TITLE)).not.toBeInTheDocument())
  })

  it('błąd trafień pokazuje `query-error`, a „Spróbuj ponownie” wraca do wyników', async () => {
    const chunks = smokeChunks()
    let calls = 0
    server.use(
      http.post(apiUrl('/api/v1/retrieval'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 })
        }
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { chunks, doc_aggs: [], total: chunks.length },
        })
      }),
    )
    await renderPage()
    const user = userEvent.setup()

    await ask(user, 'smok')

    expect(await screen.findByTestId('query-error')).toHaveTextContent(HITS_ERROR)
    // Podsumowanie działa dalej mimo błędu trafień.
    expect(await screen.findByText(SUMMARY_TEXT)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByTestId('search-hits')).toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it('zmiana filtra plików zawęża zapytanie i wraca na pierwszą stronę', async () => {
    const { retrieval } = useSmokeApi()
    await renderPage()
    const user = userEvent.setup()
    await ask(user, 'smok')
    await waitFor(() => expect(retrieval).toHaveLength(1))

    await user.click(screen.getByTestId('file-filter'))
    await user.click(await screen.findByRole('checkbox', { name: 'Smok.pdf (1)' }))

    await waitFor(() => expect(retrieval.at(-1)).toMatchObject({ page: 1, doc_ids: ['doc-1'] }))
  })

  it('paginacja przewraca stronę, a zmiana rozmiaru wraca na pierwszą', async () => {
    const chunks = Array.from({ length: 11 }, (_, index) =>
      fixtureRetrievalChunk({ id: `c${index + 1}`, similarity: 0.9 }),
    )
    const { retrieval } = useSmokeApi(chunks)
    await renderPage()
    const user = userEvent.setup()
    await ask(user, 'smok')
    await waitFor(() => expect(retrieval).toHaveLength(1))

    // Etykiety dostępności paginacji z i18n (kontrakt WP E4-H1 §„Klucze i18n”) — nie domyślne MUI.
    expect(screen.getByLabelText('Następna strona')).toBeInTheDocument()
    await user.click(screen.getByLabelText('Przejdź do strony 2'))
    expect(await screen.findByLabelText('Strona 2')).toBeInTheDocument()
    await waitFor(() => expect(retrieval.at(-1)).toMatchObject({ page: 2 }))

    await user.click(screen.getByRole('combobox', { name: PAGE_SIZE_LABEL }))
    await user.click(await screen.findByRole('option', { name: '20' }))

    await waitFor(() => expect(retrieval.at(-1)).toMatchObject({ page: 1, page_size: 20 }))
  })
})
