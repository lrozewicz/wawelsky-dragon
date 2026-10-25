/**
 * Strona wyszukiwania przy wyłączonych flagach `search_config` (kontrakt WP E4-H1 §T4):
 * `summary=false` nie uruchamia strumienia podsumowania, `related_search=false` nie pyta
 * o pytania pokrewne i nie pokazuje chipów. Trafienia działają niezależnie od obu flag.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  apiUrl,
  fixtureRetrievalChunk,
  resetSearchesFixtures,
  retrievalHandlers,
  searchFixtureApp,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { SearchPage } from './SearchPage'

afterEach(cleanup)
beforeEach(resetSearchesFixtures)

const SEARCH_ID = 'search-1'
const SEARCH_NAME = 'Wyszukiwarka testowa'
const BAR_LABEL = 'Pytanie'
const RELATED_LABEL = 'Powiązane pytanie 1'
const SSE_HEADERS = { 'Content-Type': 'text/event-stream; charset=utf-8' }

/** Dwa trafienia z różnych dokumentów (jak `smokeChunks` w `SearchPage.test.tsx`). */
function smokeChunks() {
  return [
    fixtureRetrievalChunk({ id: 'c1', document_id: 'doc-1', document_keyword: 'Smok.pdf' }),
    fixtureRetrievalChunk({ id: 'c2', document_id: 'doc-2', document_keyword: 'Legenda.txt' }),
  ]
}

/** Wyszukiwarka z nadpisanym `search_config` — flaga bez zmiany reszty konfiguracji. */
function useConfig(config: Record<string, unknown>): void {
  server.use(
    http.get(apiUrl('/api/v1/searches/:searchId'), () =>
      HttpResponse.json({
        code: 0,
        message: '',
        data: {
          ...searchFixtureApp,
          search_config: { ...searchFixtureApp.search_config, ...config },
        },
      }),
    ),
  )
}

/** MSW podsumowania i rekomendacji z licznikami — dowód, że żądanie NIE poleciało. */
function useStreamApi(): {
  completion: ReturnType<typeof vi.fn>
  recommendation: ReturnType<typeof vi.fn>
} {
  const completion = vi.fn()
  const recommendation = vi.fn()
  server.use(
    http.post(apiUrl('/api/v1/searches/:searchId/completions'), () => {
      completion()
      return new HttpResponse('data:true\n\n', { headers: SSE_HEADERS })
    }),
    http.post(apiUrl('/api/v1/chat/recommendation'), () => {
      recommendation()
      return HttpResponse.json({ code: 0, message: '', data: [RELATED_LABEL] })
    }),
  )
  return { completion, recommendation }
}

async function renderPage(): Promise<void> {
  await renderWithProviders(<SearchPage searchId={SEARCH_ID} />)
  await screen.findByText(SEARCH_NAME)
}

/** Wpisuje pytanie, wysyła Enterem i czeka na dwa trafienia (wspólny warunek wszystkich flag). */
async function ask(text: string): Promise<void> {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText(BAR_LABEL), text)
  await user.keyboard('{Enter}')
  const hits = await screen.findByTestId('search-hits')
  await waitFor(() => expect(within(hits).getAllByTestId('search-hit')).toHaveLength(2))
}

describe('SearchPage — flagi search_config', () => {
  it('summary=false: brak karty podsumowania i brak strumienia, trafienia są', async () => {
    useConfig({ summary: false })
    const { completion } = useStreamApi()
    server.use(...retrievalHandlers({ chunks: smokeChunks() }))
    await renderPage()

    await ask('smok')

    expect(screen.queryByTestId('summary-card')).not.toBeInTheDocument()
    expect(completion).not.toHaveBeenCalled()
    expect(screen.getByTestId('search-total')).toHaveTextContent(/^Znaleziono 2 wyniki$/)
  })

  it('related_search=false: brak żądania rekomendacji i brak chipów', async () => {
    useConfig({ related_search: false })
    const { recommendation } = useStreamApi()
    server.use(...retrievalHandlers({ chunks: smokeChunks() }))
    await renderPage()

    await ask('smok')

    expect(recommendation).not.toHaveBeenCalled()
    expect(screen.queryByTestId('related-chips')).not.toBeInTheDocument()
  })

  it('related_search=true: chipy pokrewne renderowane (kontrola)', async () => {
    useConfig({ related_search: true })
    const { recommendation } = useStreamApi()
    server.use(...retrievalHandlers({ chunks: smokeChunks() }))
    await renderPage()

    await ask('smok')

    expect(await screen.findByTestId('related-chips')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: RELATED_LABEL })).toBeInTheDocument()
    await waitFor(() => expect(recommendation).toHaveBeenCalledTimes(1))
  })
})
