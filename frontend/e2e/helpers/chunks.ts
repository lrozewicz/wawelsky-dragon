// Pomocniki e2e scenariusza S6-04 (kontrakt WP E3-4a §„Wymagania e2e", pkt 4): lista chunków
// dokumentu przez API (`chunks_list`) oraz seed dokumentu, z którego powstaje co najmniej
// `minChunks` chunków. `helpers.ts` nie eksportuje swojego rozpakowania koperty, więc
// powtarzamy ten sam wzorzec lokalnie.
import type { APIRequestContext } from '@playwright/test'

import { expect } from '../fixtures'
import { seedCorpus } from '../helpers'
import type { SeededCorpus, SeedOptions } from '../helpers'

const API_URL = process.env.WD_E2E_API_URL ?? ''

/** Pola chunku istotne dla scenariusza (schemat `Chunk`, kontrakt §Fakty API). */
export type ListedChunk = {
  id: string
  content: string
  available: boolean
  important_keywords: string[]
}

type Envelope<T> = { code: number; message: string; data: T }

/** Pierwsza strona listy chunków dokumentu (100 na stronę; kontrakt §Fakty API). */
export async function listChunks(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  docId: string,
): Promise<ListedChunk[]> {
  expect(API_URL, 'brak WD_E2E_API_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')
  const response = await request.get(
    `${API_URL}/api/v1/datasets/${datasetId}/documents/${docId}/chunks?page=1&page_size=100`,
    { headers: { authorization: `Bearer ${token}` } },
  )
  const body = (await response.json()) as Envelope<{ chunks: ListedChunk[] }>
  expect(response.status(), `GET chunks: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `GET chunks: ${body.message}`).toBe(0)
  return body.data.chunks
}

/** Progi seedu: dokument musi dać co najmniej `minChunks` chunków (domyślnie 2). */
export type SeedChunkedOptions = SeedOptions & { minChunks?: number }

/**
 * `seedCorpus` + kontrola liczby chunków. Scenariusz S6-04 potrzebuje dwóch kart, a liczba
 * chunków zależy od treści i progu tokenów parsera — dlatego sprawdzamy ją wprost tutaj.
 */
export async function seedChunkedDocument(
  request: APIRequestContext,
  token: string,
  options: SeedChunkedOptions,
): Promise<SeededCorpus> {
  const corpus = await seedCorpus(request, token, {
    datasetName: options.datasetName,
    documentName: options.documentName,
    documentBody: options.documentBody,
  })
  const chunks = await listChunks(request, token, corpus.datasetId, corpus.documentId)
  expect(
    chunks.length,
    `dokument ${options.documentName} dał ${String(chunks.length)} chunków`,
  ).toBeGreaterThanOrEqual(options.minChunks ?? 2)
  return corpus
}
