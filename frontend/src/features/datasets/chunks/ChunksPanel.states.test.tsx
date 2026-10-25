/**
 * Stany zapytania listy chunków (kontrakt WP E3-7 §C6): błąd pokazuje `QueryError`,
 * a „Spróbuj ponownie” powtarza żądanie GET i wraca do listy kart.
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, fixtureChunk } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { ChunksPanel } from './ChunksPanel'

afterEach(cleanup)

describe('ChunksPanel — stany zapytania', () => {
  it('błąd listy pokazuje `query-error`, a „Spróbuj ponownie” powtarza żądanie', async () => {
    let calls = 0
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/documents/:documentId/chunks'), () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ code: 101, message: 'boom', data: null })
        }
        return HttpResponse.json({
          code: 0,
          message: 'success',
          data: { chunks: [fixtureChunk({ id: 'c1', content: 'Pierwszy' })], total: 1, doc: null },
        })
      }),
    )

    const user = userEvent.setup()
    await renderWithProviders(
      <ChunksPanel datasetId="ds-1" docId="doc-1" onActivateChunk={() => undefined} />,
    )

    expect(await screen.findByTestId('query-error')).toHaveTextContent(
      'Nie udało się wczytać chunków',
    )

    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))

    expect(await screen.findByTestId('chunk-card-c1')).toBeInTheDocument()
    expect(calls).toBe(2)
  })
})
