import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { fixtureRetrievalChunk } from '../../../test/msw/handlers/retrieval'

import { ResultsCard } from './ResultsCard'
import type { ResultsCardProps } from './ResultsCard'
import type { DocAgg, RetrievalChunk, RetrievalResult } from './queries'

afterEach(cleanup)

/** Napisy z `locales/pl/retrieval.json` — test chodzi na interfejsie polskim (domyślnym w `renderWithProviders`). */
const NOT_RUN = 'Nie uruchomiono jeszcze testu. Wpisz pytanie i kliknij Uruchom.'
const EMPTY = 'Nie znaleziono pasujących wyników. Obniż próg podobieństwa lub zmień pytanie.'
const EXCLUDED = 'Filtr metadanych wykluczył wszystkie dokumenty'

/** Wynik żądania z podanymi chunkami; `total` domyślnie równa się liczbie chunków. */
function buildResult(chunks: RetrievalChunk[], total: number = chunks.length): RetrievalResult {
  return { chunks, doc_aggs: [], total }
}

function docAgg(overrides: Partial<DocAgg> = {}): DocAgg {
  return { doc_id: 'doc-1', doc_name: 'Smok.pdf', count: 2, ...overrides }
}

async function renderCard(overrides: Partial<ResultsCardProps> = {}) {
  const onDocsChange = vi.fn()
  const onPageChange = vi.fn()
  const props: ResultsCardProps = {
    result: undefined,
    loading: false,
    allDocs: [],
    selectedDocIds: [],
    page: 1,
    pageSize: 10,
    filterActive: false,
    onDocsChange,
    onPageChange,
    ...overrides,
  }

  const view = await renderWithProviders(<ResultsCard {...props} />)

  return { ...view, onDocsChange, onPageChange }
}

describe('ResultsCard', () => {
  it('pokazuje chipy procentów, nazwę dokumentu i podświetla trafienie w treści', async () => {
    await renderCard({
      result: buildResult([
        fixtureRetrievalChunk({
          similarity: 0.8512,
          term_similarity: 0.5,
          vector_similarity: 0.9,
          highlight: 'a <em>smok</em>',
        }),
      ]),
    })

    expect(screen.getByTestId('retrieval-chip-hybrid')).toHaveTextContent('Hybrydowe 85.1%')
    expect(screen.getByText('Termowe 50.0%')).toBeInTheDocument()
    expect(screen.getByText('Wektorowe 90.0%')).toBeInTheDocument()
    expect(screen.getByText('plik.pdf')).toBeInTheDocument()

    const mark = screen.getByText('smok')
    expect(mark.tagName).toBe('MARK')
    expect(screen.getByText('a')).toBeInTheDocument()
  })

  it('nie wstrzykuje HTML z `highlight` — tagi inne niż <em> znikają', async () => {
    const { container } = await renderCard({
      result: buildResult([fixtureRetrievalChunk({ highlight: '<script>x</script>' })]),
    })

    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByText('x')).toBeInTheDocument()
  })

  it('gdy `highlight` jest pusty, bierze treść z `content`', async () => {
    await renderCard({
      result: buildResult([fixtureRetrievalChunk({ content: 'Smok wawelski', highlight: null })]),
    })

    expect(screen.getByText('Smok wawelski')).toBeInTheDocument()
  })

  it('pokazuje łączną liczbę wyników', async () => {
    await renderCard({ result: buildResult([fixtureRetrievalChunk()], 3) })

    expect(screen.getByTestId('retrieval-total')).toHaveTextContent('Łącznie 3')
  })

  it('paginacja jest widoczna tylko wtedy, gdy liczba wyników przekracza rozmiar strony', async () => {
    const user = userEvent.setup()
    const { onPageChange } = await renderCard({
      result: buildResult([fixtureRetrievalChunk()], 25),
      pageSize: 10,
    })

    expect(screen.getByRole('navigation')).toBeInTheDocument()
    // MUI nadaje przyciskom stron domyślne etykiety dostępności („Go to page 3”).
    expect(screen.getByRole('button', { name: 'Go to page 3' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Go to page 3' }))

    expect(onPageChange).toHaveBeenCalledWith(3)
  })

  it('nie pokazuje paginacji, gdy liczba wyników mieści się na stronie', async () => {
    await renderCard({ result: buildResult([fixtureRetrievalChunk()], 5), pageSize: 10 })

    expect(screen.queryByRole('navigation')).toBeNull()
  })

  it('pokazuje pusty stan „nie uruchomiono”, gdy nie ma jeszcze wyniku', async () => {
    await renderCard()

    expect(screen.getByText(NOT_RUN)).toBeInTheDocument()
    expect(screen.queryByTestId('retrieval-empty')).toBeNull()
    expect(screen.queryByTestId('retrieval-total')).toBeNull()
  })

  it('pokazuje pusty stan „brak wyników”, gdy wynik jest bez chunków', async () => {
    await renderCard({ result: buildResult([], 0) })

    expect(screen.getByTestId('retrieval-empty')).toBeInTheDocument()
    expect(screen.getByText(EMPTY)).toBeInTheDocument()
    expect(screen.queryByTestId('retrieval-result')).toBeNull()
  })

  it('gdy filtr metadanych był aktywny, pusty wynik dostaje komunikat wykluczenia (SC-E6-1b-06 krok 2)', async () => {
    await renderCard({ result: buildResult([], 0), filterActive: true })

    expect(screen.getByText(EXCLUDED)).toBeInTheDocument()
    expect(screen.queryByText(EMPTY)).toBeNull()
  })

  it('bez aktywnego filtra metadanych komunikat wykluczenia nie występuje', async () => {
    await renderCard({ result: buildResult([], 0), filterActive: false })

    expect(screen.getByText(EMPTY)).toBeInTheDocument()
    expect(screen.queryByText(EXCLUDED)).toBeNull()
  })

  it('w trakcie ładowania pokazuje wskaźnik postępu', async () => {
    await renderCard({ loading: true })

    expect(screen.getByRole('progressbar')).toBeInTheDocument()
    expect(screen.queryByText(NOT_RUN)).toBeNull()
  })

  it('przycisk filtra niesie liczbę wybranych dokumentów', async () => {
    await renderCard({
      result: buildResult([fixtureRetrievalChunk()], 1),
      allDocs: [docAgg()],
      selectedDocIds: ['doc-1'],
    })

    expect(screen.getByTestId('retrieval-doc-filter')).toHaveTextContent('Filtruj dokumenty (1)')
  })

  it('wybór dokumentu w popoverze woła onDocsChange z nową listą', async () => {
    const user = userEvent.setup()
    const { onDocsChange } = await renderCard({
      result: buildResult([fixtureRetrievalChunk()], 1),
      allDocs: [docAgg(), docAgg({ doc_id: 'doc-2', doc_name: 'Legenda.pdf', count: 1 })],
    })

    expect(screen.queryByRole('checkbox')).toBeNull()

    await user.click(screen.getByTestId('retrieval-doc-filter'))
    await user.click(await screen.findByRole('checkbox', { name: 'Smok.pdf (2)' }))

    expect(onDocsChange).toHaveBeenCalledWith(['doc-1'])
  })

  it('przycisk „Wszystkie dokumenty” czyści filtr i zamyka popover', async () => {
    const user = userEvent.setup()
    const { onDocsChange } = await renderCard({
      result: buildResult([fixtureRetrievalChunk()], 1),
      allDocs: [docAgg()],
      selectedDocIds: ['doc-1'],
    })

    await user.click(screen.getByTestId('retrieval-doc-filter'))
    await user.click(await screen.findByRole('button', { name: 'Wszystkie dokumenty' }))

    expect(onDocsChange).toHaveBeenCalledWith([])
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Wszystkie dokumenty' })).not.toBeInTheDocument(),
    )
  })
})
