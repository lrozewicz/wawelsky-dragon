import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { createElement } from 'react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import { apiUrl } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'

import {
  metadataConfigQueryOptions,
  metadataKeys,
  metadataSummaryQueryOptions,
  patchDocumentMeta,
  saveMetadataConfig,
  useMetaKeys,
} from './queries'

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }): ReactNode =>
    createElement(QueryClientProvider, { client }, children)
}

const CONFIG_PATH = '/api/v1/datasets/:id/metadata/config'
const SUMMARY_PATH = '/api/v1/datasets/:id/metadata/summary'
const DOC_PATH = '/api/v1/datasets/:id/documents/:docId'

describe('metadataConfigQueryOptions', () => {
  it('czyta listę pól z `data.metadata` i mapuje null na puste pola', async () => {
    server.use(
      http.get(apiUrl(CONFIG_PATH), () =>
        HttpResponse.json({
          code: 0,
          data: {
            metadata: [{ key: 'rok', type: 'string', description: null, enum: null }],
            built_in_metadata: [],
          },
        }),
      ),
    )

    const result = await createClient().fetchQuery(metadataConfigQueryOptions('ds-1'))

    expect(result).toEqual([{ key: 'rok', description: '', enum: [] }])
    expect(metadataConfigQueryOptions('ds-1').queryKey).toEqual(metadataKeys.config('ds-1'))
  })
})

describe('saveMetadataConfig', () => {
  it('wysyła PUT z polami typu string i pustymi jako null', async () => {
    let body: unknown = null
    server.use(
      http.put(apiUrl(CONFIG_PATH), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ code: 0, data: { metadata: [], built_in_metadata: [] } })
      }),
    )

    await saveMetadataConfig('ds-1', [{ key: ' rok ', description: '', enum: [] }])

    expect(body).toEqual({
      metadata: [{ key: 'rok', type: 'string', description: null, enum: null }],
    })
  })
})

describe('metadataSummaryQueryOptions', () => {
  it('mapuje pary (wartość, liczba) na listę wartości', async () => {
    server.use(
      http.get(apiUrl(SUMMARY_PATH), () =>
        HttpResponse.json({
          code: 0,
          data: {
            summary: {
              rok: {
                type: 'string',
                values: [
                  ['2023', 2],
                  ['2024', 1],
                ],
              },
            },
          },
        }),
      ),
    )

    const result = await createClient().fetchQuery(metadataSummaryQueryOptions('ds-1'))

    expect(result).toEqual({ rok: { type: 'string', values: ['2023', '2024'] } })
    expect(metadataSummaryQueryOptions('ds-1').queryKey).toEqual(metadataKeys.summary('ds-1'))
  })
})

describe('useMetaKeys', () => {
  it('scala klucze i unikalne wartości z wielu baz w kolejności pierwszego wystąpienia', async () => {
    server.use(
      http.get(apiUrl(SUMMARY_PATH), ({ params }) =>
        HttpResponse.json({
          code: 0,
          data: {
            summary:
              params.id === 'ds-1'
                ? {
                    rok: {
                      type: 'string',
                      values: [
                        ['2023', 1],
                        ['2024', 1],
                      ],
                    },
                  }
                : {
                    rok: {
                      type: 'string',
                      values: [
                        ['2024', 1],
                        ['2025', 1],
                      ],
                    },
                    typ: { type: 'string', values: [['raport', 1]] },
                  },
          },
        }),
      ),
    )

    const { result } = renderHook(() => useMetaKeys(['ds-1', 'ds-2']), {
      wrapper: wrapper(createClient()),
    })

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.keys).toEqual({ rok: ['2023', '2024', '2025'], typ: ['raport'] })
    expect(result.current.hasAny).toBe(true)
  })

  it('brak baz i brak kluczy dają pusty stan', () => {
    const { result } = renderHook(() => useMetaKeys([]), { wrapper: wrapper(createClient()) })

    expect(result.current.keys).toEqual({})
    expect(result.current.hasAny).toBe(false)
    expect(result.current.isLoading).toBe(false)
  })

  it('uzupełnia znane wartości enumem pól z konfiguracji (SC-04: „ustawa”)', async () => {
    server.use(
      http.get(apiUrl(SUMMARY_PATH), () =>
        HttpResponse.json({
          code: 0,
          data: { summary: { typ: { type: 'string', values: [['raport', 2]] } } },
        }),
      ),
      http.get(apiUrl(CONFIG_PATH), () =>
        HttpResponse.json({
          code: 0,
          data: {
            metadata: [
              {
                key: 'typ',
                type: 'string',
                description: null,
                enum: ['raport', 'rocznik', 'ustawa'],
              },
            ],
            built_in_metadata: [],
          },
        }),
      ),
    )

    const { result } = renderHook(() => useMetaKeys(['ds-1']), {
      wrapper: wrapper(createClient()),
    })

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.keys).toEqual({ typ: ['raport', 'rocznik', 'ustawa'] })
    expect(result.current.hasAny).toBe(true)
  })

  it('pole konfiguracji bez wartości w dokumentach daje klucz z pustą listą', async () => {
    server.use(
      http.get(apiUrl(SUMMARY_PATH), () => HttpResponse.json({ code: 0, data: { summary: {} } })),
      http.get(apiUrl(CONFIG_PATH), () =>
        HttpResponse.json({
          code: 0,
          data: {
            metadata: [{ key: 'rok', type: 'string', description: null, enum: null }],
            built_in_metadata: [],
          },
        }),
      ),
    )

    const { result } = renderHook(() => useMetaKeys(['ds-1']), {
      wrapper: wrapper(createClient()),
    })

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.keys).toEqual({ rok: [] })
    expect(result.current.hasAny).toBe(true)
  })
})

describe('patchDocumentMeta', () => {
  it('wysyła PATCH z całym słownikiem `meta_fields`', async () => {
    let body: unknown = null
    server.use(
      http.patch(apiUrl(DOC_PATH), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ code: 0, data: {} })
      }),
    )

    await patchDocumentMeta('ds-1', 'doc-1', { rok: '2023', tagi: ['a'] })

    expect(body).toEqual({ meta_fields: { rok: '2023', tagi: ['a'] } })
  })
})
