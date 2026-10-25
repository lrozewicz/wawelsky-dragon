/**
 * Warstwa danych testu retrievalu (kontrakt WP E3-4b §R/queries.ts): budowa ciała żądania
 * `POST /api/v1/retrieval`, mutacja wyszukiwania i lista modeli rerank.
 * Wzór: `features/datasets/queries.ts` — mutacja przez `apiCall`, jawny typ zwrotu.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import type { UseMutationResult } from '@tanstack/react-query'

import { api, apiCall } from '../../../api/client'
import type { components } from '../../../api/schema.gen'
import { modelsListQueryOptions } from '../../chats/modelsQuery'
import { filterToWire } from '../../metadata/convert'

import { isMetaFilterActive } from './schema'
import type { RetrievalSettings } from './schema'

export type RetrievalChunk = components['schemas']['RetrievalChunk']
export type RetrievalResult = components['schemas']['RetrievalResult']
export type DocAgg = components['schemas']['DocAgg']

export type RetrievalParams = {
  datasetId: string
  question: string
  settings: RetrievalSettings
  page: number
  /** `undefined`/pusta lista = bez filtra dokumentów (kontrakt §Fakty API, DEC-144). */
  documentIds?: string[]
}

/**
 * Ciało żądania wg kontraktu. Pola opcjonalne dokładamy tylko z wartością (K4 E3-H2a): brak
 * `document_ids`/`doc_ids`/`size`/`rerank_id`/`cross_languages`/`metadata_condition` zamiast
 * jawnych `null` — bez `as any`, bez wysyłania nieznanych pól.
 */
export function buildRetrievalBody(p: RetrievalParams): components['schemas']['RetrievalRequest'] {
  const body: components['schemas']['RetrievalRequest'] = {
    question: p.question,
    dataset_ids: [p.datasetId],
    page: p.page,
    page_size: p.settings.topN,
    similarity_threshold: p.settings.similarityThreshold,
    vector_similarity_weight: p.settings.vectorWeight,
    highlight: true,
    top_k: 1024,
    // DEC-151: backend wybiera parametr testem `"knn_top_k" in body`; `null` → `int(None)` → code 102.
    // Wysyłamy więc tę samą wartość co `top_k`, a nie `null`.
    knn_top_k: 1024,
    rerank_candidates_count: 64,
    keyword: false,
  }

  if (p.documentIds !== undefined && p.documentIds.length > 0) body.document_ids = p.documentIds
  if (p.settings.rerankId !== '') body.rerank_id = p.settings.rerankId
  // E2-H2/C3 + K4: pusta lista = bez przepisywania pytania (backend `None`/brak/`[]` traktuje jak brak).
  if (p.settings.crossLanguages.length > 0) body.cross_languages = p.settings.crossLanguages
  // Filtr metadanych tylko, gdy realnie zawęża (SC-E6-1b-06); „Wyłączony” i ręczny bez
  // warunków nie wysyłają pola (kontrakt WP E6-1b §1: wyłączony = {}).
  if (isMetaFilterActive(p.settings.metaDataFilter)) {
    body.meta_data_filter = filterToWire(p.settings.metaDataFilter)
  }

  return body
}

export function useRetrieval(): UseMutationResult<RetrievalResult, Error, RetrievalParams> {
  return useMutation({
    mutationFn: (params: RetrievalParams) =>
      apiCall<RetrievalResult>(api.POST('/api/v1/retrieval', { body: buildRetrievalBody(params) })),
  })
}

/** Unikalne nazwy modeli rerank z rejestru WD; `[]` przy ładowaniu i błędzie. */
export function useRerankOptions(): string[] {
  const models = useQuery(modelsListQueryOptions())
  const names = (models.data ?? [])
    .filter((model) => model.model_type.includes('rerank'))
    .map((model) => model.name)

  return [...new Set(names)]
}
