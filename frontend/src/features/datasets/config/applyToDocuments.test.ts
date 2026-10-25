/**
 * Testy modułu „Zastosuj konfigurację do istniejących plików” (kontrakt WP E5-H8c §2).
 * MSW (wzorzec `src/test/msw`): `documentsHandlers` obsługuje listę i PATCH dokumentów, a własny
 * handler dokłada JEDYNĄ trasę, której tam nie ma — POST `…/datasets/{id}/chunks` (legacy parse).
 * Własny handler PATCH rejestrujemy PRZED handlerami dokumentów, żeby móc zaplanować błąd HTTP 500
 * i błąd sieci dla wybranego dokumentu.
 */

import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'

import { apiUrl, documentsHandlers, fixtureDocument } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import type { DocumentRow } from '../files/queries'

import {
  applyConfigToDocuments,
  listAllDocuments,
  type ApplyProgress,
  type ApplyFailure,
} from './applyToDocuments'

/** Zaplanowany wynik żądania. */
type Outcome = 'ok' | 'http500' | 'network'

type Seen = { url: string; body: unknown }

/** Rejestruje trasy MSW i zbiera ciała/adresy PATCH-y oraz POST-a parsowania. */
function setupRequests(
  initial: DocumentRow[],
  opts: { patch?: (documentId: string) => Outcome; post?: Outcome } = {},
): { patches: Seen[]; parses: Seen[] } {
  const patches: Seen[] = []
  const parses: Seen[] = []

  /** Odpowiedź wg planu; `null` gdy żądanie ma się udać. */
  const fail = (plan: Outcome) => {
    if (plan === 'network') return HttpResponse.error()
    if (plan === 'http500') {
      return HttpResponse.json({ code: 102, message: 'Serwer padł' }, { status: 500 })
    }
    return null
  }

  server.use(
    http.patch(
      apiUrl('/api/v1/datasets/:datasetId/documents/:documentId'),
      async ({ request, params }) => {
        patches.push({ url: request.url, body: await request.json() })
        return fail(opts.patch?.(String(params.documentId)) ?? 'ok') ?? okResponse()
      },
    ),
    ...documentsHandlers(initial),
    http.post(apiUrl('/api/v1/datasets/:datasetId/chunks'), async ({ request }) => {
      parses.push({ url: request.url, body: await request.json() })
      return fail(opts.post ?? 'ok') ?? HttpResponse.json({ code: 0, message: 'success' })
    }),
  )

  return { patches, parses }
}

const okResponse = () => HttpResponse.json({ code: 0, message: 'success', data: {} })

/** Rejestruje trasy, woła `applyConfigToDocuments` na `docs` i zwraca żądania oraz postęp. */
async function runApply(
  documents: DocumentRow[],
  opts: {
    patch?: (documentId: string) => Outcome
    post?: Outcome
    chunkMethod?: string
    parserConfigChanges?: Record<string, unknown>
  } = {},
): Promise<{
  failures: ApplyFailure[]
  patches: Seen[]
  parses: Seen[]
  calls: ApplyProgress[]
}> {
  const { patches, parses } = setupRequests(documents, opts)
  const calls: ApplyProgress[] = []
  const result = await applyConfigToDocuments({
    datasetId: 'ds-1',
    documents,
    chunkMethod: opts.chunkMethod,
    parserConfigChanges: opts.parserConfigChanges ?? { pages: [] },
    onProgress: (p) => calls.push(p),
  })
  return { ...result, patches, parses, calls }
}

describe('listAllDocuments', () => {
  it('pobiera 250 dokumentów w trzech żądaniach po 100 (page_size 100)', async () => {
    const docs = Array.from({ length: 250 }, (_, i) =>
      fixtureDocument({ id: `doc-${i + 1}`, name: `plik-${i + 1}.pdf` }),
    )
    const pages: string[] = []
    server.use(
      ...documentsHandlers(docs, {
        onRequest: (kind, _body, url) => {
          if (kind === 'list') pages.push(url.searchParams.get('page') ?? '')
        },
      }),
    )

    const result = await listAllDocuments('ds-1')

    expect(result).toHaveLength(250)
    expect(result.map((doc) => doc.id)).toEqual(docs.map((doc) => doc.id))
    expect(pages).toEqual(['1', '2', '3'])
  })

  it('wysyła stronicę 1 z rozmiarem 100 i adres datasetu', async () => {
    const urls: URL[] = []
    server.use(
      ...documentsHandlers([fixtureDocument()], {
        onRequest: (kind, _body, url) => {
          if (kind === 'list') urls.push(url)
        },
      }),
    )

    await listAllDocuments('ds-7')

    expect(urls).toHaveLength(1)
    expect(urls[0]?.pathname).toBe('/api/v1/datasets/ds-7/documents')
    expect(urls[0]?.searchParams.get('page')).toBe('1')
    expect(urls[0]?.searchParams.get('page_size')).toBe('100')
  })

  it('propaguje błąd pobrania listy (HTTP 500) z koperty', async () => {
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/documents'), () =>
        HttpResponse.json({ code: 102, message: 'Brak dostępu' }, { status: 500 }),
      ),
    )

    await expect(listAllDocuments('ds-1')).rejects.toThrow('Brak dostępu')
  })

  it('pusta strona przy total > 0 kończy pętlę po pierwszym żądaniu', async () => {
    const urls: URL[] = []
    server.use(
      http.get(apiUrl('/api/v1/datasets/:datasetId/documents'), ({ request }) => {
        urls.push(new URL(request.url))
        return HttpResponse.json({ code: 0, message: 'success', data: { docs: [], total: 5 } })
      }),
    )

    expect(await listAllDocuments('ds-1')).toEqual([])
    expect(urls).toHaveLength(1)
  })
})

describe('applyConfigToDocuments', () => {
  it('scala parser_config, wysyła jedno POST i raportuje postęp 1/1', async () => {
    const doc = fixtureDocument({
      id: 'doc-1',
      name: 'raport.pdf',
      parser_config: { chunk_token_num: 512, pages: [[2, 3]] },
    })

    const { failures, patches, parses, calls } = await runApply([doc])

    expect(patches).toHaveLength(1)
    expect(patches[0]?.url).toContain('/api/v1/datasets/ds-1/documents/doc-1')
    // Bez `chunk_method` w args klucz nie trafia do ciała (kontrakt §2).
    expect(patches[0]?.body).toEqual({ parser_config: { chunk_token_num: 512, pages: [] } })
    expect(parses).toHaveLength(1)
    expect(parses[0]?.url).toContain('/api/v1/datasets/ds-1/chunks')
    expect(parses[0]?.body).toEqual({ document_ids: ['doc-1'] })
    expect(failures).toEqual([])
    expect(calls).toEqual([{ done: 1, total: 1 }])
  })

  it('dokłada chunk_method do ciała PATCH, gdy podany w args', async () => {
    const doc = fixtureDocument({ id: 'doc-1', parser_config: { chunk_token_num: 512 } })

    const { patches } = await runApply([doc], {
      chunkMethod: 'naive',
      parserConfigChanges: { layout_recognize: 'fake-vision' },
    })

    expect(patches[0]?.body).toEqual({
      chunk_method: 'naive',
      parser_config: { chunk_token_num: 512, layout_recognize: 'fake-vision' },
    })
  })

  it('błąd jednego pliku trafia do failures, a pozostałe lecą dalej (bez niego w POST)', async () => {
    const docs = [
      fixtureDocument({ id: 'doc-1', name: 'a.pdf' }),
      fixtureDocument({ id: 'doc-2', name: 'b.pdf' }),
      fixtureDocument({ id: 'doc-3', name: 'c.pdf' }),
    ]

    const { failures, patches, parses, calls } = await runApply(docs, {
      patch: (id) => (id === 'doc-2' ? 'http500' : 'ok'),
    })

    expect(patches).toHaveLength(3)
    expect(failures).toEqual([
      { documentId: 'doc-2', name: 'b.pdf', message: 'Serwer padł', code: 102 },
    ])
    expect(parses).toHaveLength(1)
    expect(parses[0]?.body).toEqual({ document_ids: ['doc-1', 'doc-3'] })
    expect(calls).toEqual([
      { done: 1, total: 3 },
      { done: 2, total: 3 },
      { done: 3, total: 3 },
    ])
  })

  it('błąd inny niż ApiError opisuje String(error), a nie POST-uje nic', async () => {
    const { failures, parses, calls } = await runApply([fixtureDocument({ id: 'doc-1' })], {
      patch: () => 'network',
    })

    expect(failures).toHaveLength(1)
    expect(failures[0]?.documentId).toBe('doc-1')
    // Błąd transportu nie jest `ApiError` → idzie ścieżka `String(error)`.
    expect(failures[0]?.message).toMatch(/TypeError/)
    // Zero udanych → brak POST `…/chunks` (kontrakt §2 p. 4).
    expect(parses).toEqual([])
    expect(calls).toEqual([{ done: 1, total: 1 }])
  })

  it('nie wysyła POST-a, gdy nie ma żadnego udanego pliku', async () => {
    const { failures, parses } = await runApply([fixtureDocument({ id: 'doc-1' })], {
      patch: () => 'http500',
    })

    expect(failures).toHaveLength(1)
    expect(parses).toEqual([])
  })

  it('błąd POST-a parsowania propaguje wyjątek, a nie wpis w failures', async () => {
    const docs = [fixtureDocument({ id: 'doc-1' }), fixtureDocument({ id: 'doc-2' })]
    const { patches, parses } = setupRequests(docs, { post: 'http500' })
    const calls: ApplyProgress[] = []

    await expect(
      applyConfigToDocuments({
        datasetId: 'ds-1',
        documents: docs,
        parserConfigChanges: { pages: [] },
        onProgress: (p) => calls.push(p),
      }),
    ).rejects.toThrow('Serwer padł')

    // Wszystkie PATCH-e poszły (i raportowały postęp) przed jednym POST-em.
    expect(parses).toHaveLength(1)
    expect(patches).toHaveLength(2)
    expect(calls).toEqual([
      { done: 1, total: 2 },
      { done: 2, total: 2 },
    ])
  })

  it('obsługuje puste documents bez żadnego żądania', async () => {
    const { failures, patches, parses, calls } = await runApply([])

    expect(failures).toEqual([])
    expect(patches).toEqual([])
    expect(parses).toEqual([])
    expect(calls).toEqual([])
  })

  it('przetwarza dokumenty po kolei — drugi PATCH rusza po odpowiedzi pierwszego', async () => {
    const docs = [fixtureDocument({ id: 'doc-1' }), fixtureDocument({ id: 'doc-2' })]
    const completed: string[] = []
    server.use(
      http.patch(
        apiUrl('/api/v1/datasets/:datasetId/documents/:documentId'),
        async ({ params }) => {
          const documentId = String(params.documentId)
          if (documentId === 'doc-1') await new Promise((resolve) => setTimeout(resolve, 30))
          completed.push(documentId)
          return okResponse()
        },
      ),
      http.post(apiUrl('/api/v1/datasets/:datasetId/chunks'), () =>
        HttpResponse.json({ code: 0, message: 'success' }),
      ),
    )

    await applyConfigToDocuments({
      datasetId: 'ds-1',
      documents: docs,
      parserConfigChanges: {},
      onProgress: () => {},
    })

    expect(completed).toEqual(['doc-1', 'doc-2'])
  })
})
