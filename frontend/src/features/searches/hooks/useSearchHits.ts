/**
 * Hook trafień wyszukiwania (kontrakt WP E4-4b §3): `POST /api/v1/retrieval` z ciałem budowanym
 * z `search_config` wyszukiwarki (wzór: `buildRetrievalBody` z `features/datasets/retrieval`).
 * Paginacja bez migotania (`keepPreviousData`); przy `null` żądanie nie leci.
 */

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api, apiCall } from '../../../api/client'
import type { components } from '../../../api/schema.gen'

import type { RawSearchConfig } from '../queries'

import type { RetrievalResult } from '../../datasets/retrieval/queries'

export type { RetrievalResult }

export type SearchHitsParams = {
  question: string
  /** `search_config` wyszukiwarki (`Record<string, unknown>`). */
  config: RawSearchConfig
  /** Numer strony od 1. */
  page: number
  /** Rozmiar strony: 10 | 20 | 50. */
  pageSize: number
  /** Filtr plików; pusta lista = bez filtra. */
  docIds: string[]
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === 'number' ? value : fallback
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/**
 * Aktywność filtra w formacie drutu (`search_config.meta_data_filter`) — jak `isMetaFilterActive`
 * w `buildRetrievalBody`: „Wyłączony” (i nieznany kształt) oraz ręczny bez warunków niczego
 * nie odfiltrowują (kontrakt WP E6-1b §1).
 */
function isWireFilterActive(filter: Record<string, unknown>): boolean {
  if (filter.method === 'manual') return Array.isArray(filter.manual) && filter.manual.length > 0
  return filter.method === 'auto' || filter.method === 'semi_auto'
}

/**
 * Ciało żądania wg kontraktu: progi z `config` (domyślnie 0.2/0.3), pola opcjonalne tylko
 * z wartością (`rerank_id`, `doc_ids`) — bez jawnych `null` (jak `buildRetrievalBody`).
 */
export function buildHitsBody(p: SearchHitsParams): components['schemas']['RetrievalRequest'] {
  const body: components['schemas']['RetrievalRequest'] = {
    question: p.question,
    dataset_ids: stringList(p.config.kb_ids),
    page: p.page,
    page_size: p.pageSize,
    similarity_threshold: numberOr(p.config.similarity_threshold, 0.2),
    vector_similarity_weight: numberOr(p.config.vector_similarity_weight, 0.3),
    highlight: true,
    top_k: 1024,
    knn_top_k: 1024,
    rerank_candidates_count: 64,
    keyword: false,
  }

  const rerankId = p.config.rerank_id
  if (typeof rerankId === 'string' && rerankId !== '') body.rerank_id = rerankId
  if (p.docIds.length > 0) body.doc_ids = p.docIds

  // Filtr metadanych (E6-1b): `search_config.meta_data_filter` (już w formacie drutu po zapisie)
  // idzie do /retrieval tylko, gdy realnie zawęża — spójnie z `buildRetrievalBody`
  // (`isMetaFilterActive`): „Wyłączony” = `{}`, a ręczny bez warunków niczego nie odfiltrowuje.
  const metaDataFilter = p.config.meta_data_filter
  if (isRecord(metaDataFilter) && isWireFilterActive(metaDataFilter)) {
    body.meta_data_filter = metaDataFilter
  }

  return body
}

export function useSearchHits(p: SearchHitsParams | null): UseQueryResult<RetrievalResult> {
  return useQuery({
    queryKey: ['searches', 'hits', p],
    enabled: p !== null,
    // Poprzednia strona zostaje w cache, gdy leci nowa.
    placeholderData: keepPreviousData,
    queryFn: () =>
      apiCall<RetrievalResult>(api.POST('/api/v1/retrieval', { body: buildHitsBody(p!) })),
  })
}
