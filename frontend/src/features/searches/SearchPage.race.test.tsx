/**
 * Wyścig pytania z wczytaniem `search_config` (defekt QA-UI E4-4b): ekran startowy renderuje pasek
 * jeszcze przed odpowiedzią `GET /searches/:id`, więc wysłane wtedy pytanie poszłoby do retrievalu
 * z pustą konfiguracją (bez `kb_ids` i progów). Do czasu wczytania wyszukiwarki pytanie jest
 * ignorowane, a po wczytaniu działa jak dotąd — z konfiguracją z `search_config`.
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'
import {
  apiUrl,
  fixtureRetrievalChunk,
  resetSearchesFixtures,
  retrievalHandlers,
  searchFixtureApp,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import { SearchPage } from './SearchPage'

afterEach(cleanup)
beforeEach(resetSearchesFixtures)

// Napisy z `locales/pl/searches.json` — interfejs polski jest domyślny w `renderWithProviders`.
const SEARCH_ID = 'search-1'
const SEARCH_NAME = 'Wyszukiwarka testowa'
const BAR_LABEL = 'Pytanie'
const QUESTION = 'smok'

/**
 * MSW `GET /searches/:id` wstrzymany do zwolnienia bramki — deterministyczne okno wyścigu
 * (stałe opóźnienie `delay` jest wrażliwe na obciążenie maszyny, więc test bywał flaky).
 * Zwraca funkcję zwalniającą odpowiedź.
 */
function holdSearchResponse(): () => void {
  let release = (): void => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  server.use(
    http.get(apiUrl('/api/v1/searches/:searchId'), async () => {
      await gate
      return HttpResponse.json({ code: 0, message: '', data: searchFixtureApp })
    }),
  )
  return release
}

/** MSW trafień + rejestr ciał żądań `POST /api/v1/retrieval`. */
function useRetrieval(): Record<string, unknown>[] {
  const retrieval: Record<string, unknown>[] = []
  server.use(
    ...retrievalHandlers({
      chunks: [fixtureRetrievalChunk({ id: 'c1', similarity: 0.9 })],
      onRequest: (body) => retrieval.push(body),
    }),
  )
  return retrieval
}

describe('SearchPage — wyścig z wczytaniem search_config', () => {
  it('pytanie przed wczytaniem wyszukiwarki nic nie wysyła, a po wczytaniu niesie kb_ids', async () => {
    const releaseSearch = holdSearchResponse()
    const retrieval = useRetrieval()
    await renderWithProviders(<SearchPage searchId={SEARCH_ID} />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(BAR_LABEL), QUESTION)
    await user.keyboard('{Enter}')

    // Wyszukiwarka jeszcze się nie wczytała — retrieval nie może polecieć z pustą konfiguracją.
    expect(retrieval).toHaveLength(0)

    releaseSearch()
    await screen.findByText(SEARCH_NAME)
    await user.keyboard('{Enter}')

    await waitFor(() => expect(retrieval).toHaveLength(1))
    expect(retrieval[0]).toMatchObject({ question: QUESTION, dataset_ids: ['ds-1'] })
  })

  it('po wczytaniu wyszukiwarki pytanie działa jak dotąd', async () => {
    const retrieval = useRetrieval()
    await renderWithProviders(<SearchPage searchId={SEARCH_ID} />)
    await screen.findByText(SEARCH_NAME)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(BAR_LABEL), QUESTION)
    await user.keyboard('{Enter}')

    await waitFor(() => expect(retrieval).toHaveLength(1))
    expect(retrieval[0]).toMatchObject({ question: QUESTION, dataset_ids: ['ds-1'] })
  })
})
