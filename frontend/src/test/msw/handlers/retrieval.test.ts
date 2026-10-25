import { describe, expect, it } from 'vitest'

import { server } from '../server'

import { apiUrl } from './common'
import { fixtureRetrievalChunk, retrievalHandlers } from './retrieval'

// Handlery MSW testu retrievalu (kontrakt WP E3-H2a §K4, DEC-155): odrzucenie `knn_top_k: null`
// i `cross_languages` niebędącego listą kodem 102 (HTTP 409, jak `Conflict` backendu).
const jsonHeaders = { 'Content-Type': 'application/json' }

async function post(body: Record<string, unknown>): Promise<Response> {
  server.use(...retrievalHandlers({ chunks: [fixtureRetrievalChunk()] }))
  return fetch(apiUrl('/api/v1/retrieval'), {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(body),
  })
}

describe('handlery MSW — retrieval (K4/DEC-155)', () => {
  it('odrzuca knn_top_k === null kodem 102', async () => {
    const response = await post({ question: 'q', dataset_ids: ['ds-1'], knn_top_k: null })

    expect(response.status).toBe(409)
    const body = (await response.json()) as { code: number; message: string }
    expect(body.code).toBe(102)
    expect(body.message).not.toBe('')
  })

  it('odrzuca cross_languages niebędące listą kodem 102', async () => {
    const response = await post({ question: 'q', dataset_ids: ['ds-1'], cross_languages: 'German' })

    expect(response.status).toBe(409)
    const body = (await response.json()) as { code: number }
    expect(body.code).toBe(102)
  })

  it('filtruje po aliasie doc_ids tak samo jak po document_ids', async () => {
    const chunks = [
      fixtureRetrievalChunk({ id: 'chunk-1', document_id: 'doc-1' }),
      fixtureRetrievalChunk({ id: 'chunk-2', document_id: 'doc-2' }),
    ]
    server.use(...retrievalHandlers({ chunks }))

    const send = (field: string): Promise<Response> =>
      fetch(apiUrl('/api/v1/retrieval'), {
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({ question: 'q', dataset_ids: ['ds-1'], [field]: ['doc-1'] }),
      })

    const byContractName = await send('document_ids')
    const byAlias = await send('doc_ids')

    const contractBody = (await byContractName.json()) as { data: { total: number } }
    const aliasBody = (await byAlias.json()) as {
      data: { total: number; chunks: { document_id: string }[] }
    }
    expect(aliasBody.data.total).toBe(1)
    expect(aliasBody.data.chunks.map((chunk) => chunk.document_id)).toEqual(['doc-1'])
    expect(aliasBody.data).toEqual(contractBody.data)
  })

  it('przyjmuje cross_languages jako listę i brak klucza', async () => {
    const withList = await post({
      question: 'q',
      dataset_ids: ['ds-1'],
      cross_languages: ['German'],
    })
    const withoutKey = await post({ question: 'q', dataset_ids: ['ds-1'] })

    expect(withList.status).toBe(200)
    expect(withoutKey.status).toBe(200)
    const body = (await withList.json()) as { code: number }
    expect(body.code).toBe(0)
  })
})
