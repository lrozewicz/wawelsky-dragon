/**
 * „Zastosuj konfigurację do istniejących plików” (kontrakt WP E5-H8c §2): pobranie WSZYSTKICH
 * dokumentów datasetu (`page_size` 100, pętla po stronach do `total`), PATCH każdego dokumentu
 * po kolei (obciążenie API — bez równoległości) z scaloną konfiguracją i JEDNO POST
 * `/datasets/{id}/chunks`, które uruchamia parsowanie ponowne wyłącznie udanych plików.
 * Inwalidacja cache należy do wywołującego (UI, T6).
 */

import { api, apiCall } from '../../../api/client'
import { ApiError } from '../../../api/envelope'
import { unwrapList } from '../../../api/lists'
import type { DocumentRow } from '../files/queries'

export type ApplyProgress = { done: number; total: number }
export type ApplyFailure = {
  documentId: string
  name: string
  message: string
  /** Kod koperty RAGFlow z `ApiError` — tłumaczenie komunikatu przy wyświetleniu (T3b). */
  code?: number
}

/** Rozmiar strony pobierania dokumentów (kontrakt §2). */
const PAGE_SIZE = 100

/** Pobiera WSZYSTKIE dokumenty datasetu (page_size 100, pętla po stronach do total). */
export async function listAllDocuments(datasetId: string): Promise<DocumentRow[]> {
  const all: DocumentRow[] = []
  for (let page = 1; ; page += 1) {
    const { data, error, response } = await api.GET('/api/v1/datasets/{dataset_id}/documents', {
      params: { path: { dataset_id: datasetId }, query: { page, page_size: PAGE_SIZE } },
    })
    const { items, total } = unwrapList<DocumentRow>(
      'documents',
      response.ok ? data : error,
      response.status,
    )
    all.push(...items)
    // Pusta strona przy niezerowym `total` nie ma prawa zdarzyć się u zdrowego backendu, ale bez
    // tego wyjścia pętla nigdy by się nie skończyła — a to akcja użytkownika w przeglądarce.
    if (items.length === 0 || all.length >= total) break
  }
  return all
}

/**
 * Dla każdego dokumentu: PATCH `{chunk_method?, parser_config: {...doc.parser_config, ...changed}}`;
 * potem JEDNO POST `…/datasets/{id}/chunks {document_ids: [tylko udane]}`.
 */
export async function applyConfigToDocuments(args: {
  datasetId: string
  documents: DocumentRow[]
  chunkMethod?: string
  parserConfigChanges: Record<string, unknown>
  onProgress: (p: ApplyProgress) => void
}): Promise<{ failures: ApplyFailure[] }> {
  const { datasetId, documents, chunkMethod, parserConfigChanges, onProgress } = args
  const failures: ApplyFailure[] = []
  const applied: string[] = []

  for (const doc of documents) {
    const body: { chunk_method?: string; parser_config: Record<string, unknown> } = {
      parser_config: { ...doc.parser_config, ...parserConfigChanges },
    }
    if (chunkMethod !== undefined) body.chunk_method = chunkMethod
    try {
      await apiCall<DocumentRow>(
        api.PATCH('/api/v1/datasets/{dataset_id}/documents/{document_id}', {
          params: { path: { dataset_id: datasetId, document_id: doc.id } },
          body,
        }),
      )
      applied.push(doc.id)
    } catch (error) {
      failures.push({
        documentId: doc.id,
        name: doc.name,
        message: error instanceof ApiError ? error.message : String(error),
        ...(error instanceof ApiError ? { code: error.code } : {}),
      })
    }
    onProgress({ done: applied.length + failures.length, total: documents.length })
  }

  if (applied.length > 0) {
    await apiCall<undefined>(
      api.POST('/api/v1/datasets/{dataset_id}/chunks', {
        params: { path: { dataset_id: datasetId } },
        body: { document_ids: applied },
      }),
    )
  }

  return { failures }
}
