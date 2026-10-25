// Pomocnik fake-ocr dla scenariuszy Stop/OCR (WP E5-H8a T7, kontrakt §C6): opóźnienie i liczniki
// z endpointów administracyjnych fake-llm oraz rejestracja modelu `fake-ocr` w rejestrze tenantu.
// Rejestracja jest potrzebna, bo reset K9 zasiewa tylko `fake-vision` (backend/app/services/reset.py),
// a `layout_recognize` waliduje nazwę po rejestrze (datasets_layout.py) — bez wpisu PUT odrzuci
// parser `fake-ocr` zanim worker cokolwiek sparsuje.
import type { APIRequestContext, APIResponse } from '@playwright/test'

import { expect } from '../fixtures'

const API_URL = process.env.WD_E2E_API_URL ?? ''

/** Adres fake-llm bez końcówki `/v1` (endpointy `/v1/fake/*` siedzą na tym samym porcie). */
function llmUrl(): string {
  const url = (process.env.WD_LLM_BASE_URL ?? '').replace(/\/v1\/?$/, '')
  expect(url, 'brak WD_LLM_BASE_URL — uruchom scenariusz przez `bun run e2e`').not.toBe('')
  return url
}

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow (trasy `/api/v1/*`): HTTP 200 + `code 0`, inaczej `expect` rzuca. */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** fake-llm odpowiada BEZ koperty RAGFlow (surowy JSON `/v1/fake/*`), więc osobny rozwijacz. */
async function fakeOk<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  expect(response.status(), `${label}: HTTP ${response.status()}`).toBe(200)
  return (await response.json()) as T
}

export type FakeStats = { chat_completions: Record<string, number> }

/** Ustawia opóźnienie `fake-ocr` na stronę w ms (C6: `POST /v1/fake/ocr-delay`). */
export async function setOcrDelay(request: APIRequestContext, ms: number): Promise<void> {
  const data = await fakeOk<{ ms: number }>(
    request.post(`${llmUrl()}/v1/fake/ocr-delay`, { data: { ms } }),
    'POST /v1/fake/ocr-delay',
  )
  expect(data.ms, 'opóźnienie fake-ocr po ustawieniu').toBe(ms)
}

/** Odczyt liczników żądań per model (C6: `GET /v1/fake/stats`). */
export async function fakeStats(request: APIRequestContext): Promise<FakeStats> {
  return fakeOk<FakeStats>(request.get(`${llmUrl()}/v1/fake/stats`), 'GET /v1/fake/stats')
}

/** Licznik żądań danego modelu (0, gdy model jeszcze nie odpowiadał). */
export function ocrCount(stats: FakeStats, model: string): number {
  return stats.chat_completions[model] ?? 0
}

/** Zeruje liczniki żądań (C6: `POST /v1/fake/stats/reset`); opóźnienia nie rusza. */
export async function resetFakeStats(request: APIRequestContext): Promise<void> {
  await fakeOk<unknown>(
    request.post(`${llmUrl()}/v1/fake/stats/reset`),
    'POST /v1/fake/stats/reset',
  )
}

/**
 * Rejestruje model `fake-ocr` (image2text) na tej samej instancji bramki, na której siedzi
 * zasiany `fake-vision` (K13 §4 p. 6: model dostaje provider/instancję, base_url bierze z
 * instancji — czyli fake-llm ze stosu testowego). Wywoływać PO KAŻDYM `resetDb` (reset czyści
 * rejestr tenantu razem z tym wpisem).
 */
export async function registerFakeOcrModel(
  request: APIRequestContext,
  token: string,
): Promise<void> {
  const headers = { authorization: `Bearer ${token}` }
  const models = await ok<{ name: string; provider_name: string; instance_name: string }[]>(
    request.get(`${API_URL}/api/v1/models`, { headers }),
    'GET /api/v1/models',
  )
  const vision = models.find((model) => model.name === 'fake-vision')
  expect(vision, 'fake-vision w rejestrze po resecie K9').toBeDefined()
  await ok<unknown>(
    request.post(
      `${API_URL}/api/v1/providers/${vision!.provider_name}/instances/${vision!.instance_name}/models`,
      { headers, data: { model_name: 'fake-ocr', model_type: 'image2text' } },
    ),
    'POST /providers/{name}/instances/{instance}/models',
  )
}

/** Ustawia parser PDF datasetu na model wizji (ten sam PUT, co zapis karty Konfiguracja). */
export async function setVisionParser(
  request: APIRequestContext,
  token: string,
  datasetId: string,
  model: string,
): Promise<void> {
  await ok<unknown>(
    request.put(`${API_URL}/api/v1/datasets/${datasetId}`, {
      headers: { authorization: `Bearer ${token}` },
      data: { parser_config: { layout_recognize: model } },
    }),
    'PUT /api/v1/datasets/{id}',
  )
}
