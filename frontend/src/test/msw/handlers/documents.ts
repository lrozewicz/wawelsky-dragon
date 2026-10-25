import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import type { DocumentRow } from '../../../features/datasets/files/queries'
import { apiUrl } from './common'

/** Pełny wiersz listy dokumentów (`DocumentListed` z backend/openapi.json, kontrakt §T1a). */
export function fixtureDocument(overrides: Partial<DocumentRow> = {}): DocumentRow {
  return {
    id: 'doc-1',
    name: 'plik.pdf',
    suffix: 'pdf',
    type: 'pdf',
    size: 1024,
    run: 'UNSTART',
    progress: 0,
    progress_msg: '',
    process_begin_at: null,
    process_duration: 0,
    chunk_count: 0,
    chunk_method: 'naive',
    create_time: 1_700_000_000_000,
    status: '1',
    dataset_id: 'ds-1',
    created_by: 'tenant-1',
    location: 'doc-1.pdf',
    parser_config: {},
    pipeline_id: null,
    source_type: 'local',
    thumbnail: '',
    token_count: 0,
    create_date: '2025-01-01 00:00:00',
    update_date: '2025-01-01 00:00:00',
    update_time: 1_700_000_000_000,
    meta_fields: {},
    nickname: 'recorder',
    pipeline_name: null,
    ...overrides,
  }
}

/** Kod `run` (0–5) ↔ nazwa (kontrakt §Fakty API). */
const RUN_CODE_TO_NAME: Record<string, DocumentRow['run']> = {
  '0': 'UNSTART',
  '1': 'RUNNING',
  '2': 'CANCEL',
  '3': 'DONE',
  '4': 'FAIL',
  '5': 'SCHEDULE',
}

/** Powtórzone klucze `name` i `name[]` (openapi-fetch wysyła `run`, backend przyjmuje oba). */
function readRepeatParam(url: URL, name: string): string[] {
  return [...url.searchParams.getAll(name), ...url.searchParams.getAll(`${name}[]`)].flatMap(
    (value) => value.split(','),
  )
}

/**
 * Handlery dokumentów datasetu z pamięcią stanu (wzór `datasetHandlers`): lista z filtrami,
 * upload, aktualizacja, usuwanie, parsowanie, zatrzymanie, zmiana statusu i pobieranie
 * (kontrakt WP E3-3b §T1a). Każde wywołanie daje świeży magazyn, a `server.resetHandlers()`
 * wraca między testami do stanu z `handlers`. `options.onRequest` dostaje rodzaj operacji, ciało
 * żądania i adres (GET listy przekazuje `null` jako ciało).
 */
export function documentsHandlers(
  initial: DocumentRow[] = [],
  options: {
    onRequest?: (
      kind: 'list' | 'upload' | 'update' | 'delete' | 'parse' | 'stop' | 'batch',
      body: unknown,
      url: URL,
    ) => void
  } = {},
): HttpHandler[] {
  const store = new Map(initial.map((doc) => [doc.id, { ...doc }]))
  let nextId = store.size + 1

  const notFound = () => HttpResponse.json({ code: 102, message: 'Document not found', data: null })

  const updateRuns = (ids: string[], run: DocumentRow['run']) => {
    let count = 0
    for (const id of ids) {
      const doc = store.get(id)
      if (doc !== undefined) {
        store.set(id, { ...doc, run })
        count += 1
      }
    }
    return count
  }

  return [
    // Trasy statyczne (parse/stop/batch) PRZED `documents/:documentId` — MSW bierze pierwszy
    // pasujący handler w kolejności rejestracji.
    http.post(apiUrl('/api/v1/datasets/:datasetId/documents/parse'), async ({ request }) => {
      const body = (await request.json()) as { document_ids?: string[] }
      options.onRequest?.('parse', body, new URL(request.url))
      const count = updateRuns(body.document_ids ?? [], 'SCHEDULE')
      return HttpResponse.json({ code: 0, message: 'success', data: { success_count: count } })
    }),

    http.post(apiUrl('/api/v1/datasets/:datasetId/documents/stop'), async ({ request }) => {
      const body = (await request.json()) as { document_ids?: string[] }
      options.onRequest?.('stop', body, new URL(request.url))
      const count = updateRuns(body.document_ids ?? [], 'CANCEL')
      return HttpResponse.json({ code: 0, message: 'success', data: { success_count: count } })
    }),

    http.post(
      apiUrl('/api/v1/datasets/:datasetId/documents/batch-update-status'),
      async ({ request }) => {
        const body = (await request.json()) as {
          doc_ids?: string[]
          status?: DocumentRow['status']
        }
        options.onRequest?.('batch', body, new URL(request.url))
        const result: Record<string, { status: DocumentRow['status'] }> = {}
        for (const id of body.doc_ids ?? []) {
          const doc = store.get(id)
          if (doc !== undefined && body.status !== undefined) {
            store.set(id, { ...doc, status: body.status })
            result[id] = { status: body.status }
          }
        }
        return HttpResponse.json({ code: 0, message: 'success', data: result })
      },
    ),

    http.get(apiUrl('/api/v1/datasets/:datasetId/documents'), ({ request }) => {
      const url = new URL(request.url)
      options.onRequest?.('list', null, url)
      const keywords = url.searchParams.get('keywords')?.toLowerCase() ?? ''
      const runs = readRepeatParam(url, 'run').map((code) => RUN_CODE_TO_NAME[code] ?? code)
      const suffixes = readRepeatParam(url, 'suffix')
      const orderby = url.searchParams.get('orderby') ?? 'create_time'
      const desc = url.searchParams.get('desc') !== 'false'

      const matched = [...store.values()].filter(
        (doc) =>
          (keywords === '' || doc.name.toLowerCase().includes(keywords)) &&
          (runs.length === 0 || runs.includes(doc.run)) &&
          (suffixes.length === 0 || suffixes.includes(doc.suffix)),
      )
      const sorted = [...matched].sort((a, b) => {
        // `orderby=name` (kontrakt WP E3-H2a §K1) — jak backend, kolacją bez rozróżniania wielkości.
        if (orderby === 'name') {
          const diff = a.name.localeCompare(b.name, 'pl', { sensitivity: 'base' })
          return desc ? -diff : diff
        }
        const field = orderby === 'update_time' ? 'update_time' : 'create_time'
        const diff = a[field] - b[field]
        return desc ? -diff : diff
      })
      const page = Number(url.searchParams.get('page') ?? '1')
      const pageSize = Number(url.searchParams.get('page_size') ?? '10')
      const from = (page - 1) * pageSize
      return HttpResponse.json({
        code: 0,
        message: 'success',
        data: { docs: sorted.slice(from, from + pageSize), total: matched.length },
      })
    }),

    http.post(apiUrl('/api/v1/datasets/:datasetId/documents'), async ({ request, params }) => {
      const form = await request.formData()
      options.onRequest?.('upload', form, new URL(request.url))
      const datasetId = String(params.datasetId)
      const created = form
        .getAll('file')
        .filter((entry): entry is File => entry instanceof File)
        .map((file) => {
          const doc = fixtureDocument({
            id: `doc-${nextId}`,
            name: file.name,
            suffix: file.name.split('.').pop() ?? '',
            dataset_id: datasetId,
          })
          nextId += 1
          store.set(doc.id, doc)
          return doc
        })
      return HttpResponse.json({ code: 0, message: 'success', data: created })
    }),

    http.patch(
      apiUrl('/api/v1/datasets/:datasetId/documents/:documentId'),
      async ({ request, params }) => {
        const body = (await request.json()) as {
          name?: string | null
          enabled?: 0 | 1 | null
          chunk_method?: string | null
        }
        options.onRequest?.('update', body, new URL(request.url))
        const current = store.get(String(params.documentId))
        if (current === undefined) return notFound()
        const updated: DocumentRow = {
          ...current,
          ...(body.name != null ? { name: body.name } : {}),
          ...(body.chunk_method != null ? { chunk_method: body.chunk_method } : {}),
          ...(body.enabled != null
            ? { status: String(body.enabled) as DocumentRow['status'] }
            : {}),
        }
        store.set(updated.id, updated)
        return HttpResponse.json({ code: 0, message: 'success', data: updated })
      },
    ),

    http.delete(apiUrl('/api/v1/datasets/:datasetId/documents'), async ({ request }) => {
      const body = (await request.json()) as { ids?: string[] }
      options.onRequest?.('delete', body, new URL(request.url))
      const ids = body.ids ?? []
      for (const id of ids) store.delete(id)
      return HttpResponse.json({ code: 0, message: 'success', data: { deleted: ids.length } })
    }),

    // Pobieranie pliku (`documents_download`) — `text/plain` z ciała string; rejestrowane na końcu,
    // aby nie przechwyciło tras statycznych wyżej. Ciało jako `Blob` nie działa w jsdom (brak
    // `Blob.stream()`) i MSW odpowiadałoby 500.
    http.get(apiUrl('/api/v1/datasets/:datasetId/documents/:documentId'), ({ params }) => {
      const doc = store.get(String(params.documentId))
      if (doc === undefined) return notFound()
      return new HttpResponse(doc.name, { headers: { 'content-type': 'text/plain' } })
    }),
  ]
}
