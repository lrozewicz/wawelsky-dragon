import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import { apiUrl } from './common'

// Odpowiednik `DefaultModels` z backend/openapi.json (GET /api/v1/users/me/models).
export type FixtureModels = {
  llm_id: string
  embd_id: string
  img2txt_id: string
  rerank_id: string
  asr_id: string
  tts_id: string
}

export const fixtureModels: FixtureModels = {
  llm_id: 'fake-llm',
  embd_id: 'fake-embd',
  img2txt_id: '',
  rerank_id: '',
  asr_id: '',
  tts_id: '',
}

// Odpowiednik `Model` z backend/openapi.json (GET /api/v1/models) — pola jak w złocie
// backend/tests/contract/golden/v0.27.2/models/system--11.json.
export type FixtureModel = {
  model_id: string
  tenant_id: string
  tenant_name: string
  model_type: string[]
  name: string
  provider_id: string
  provider_name: string
  instance_id: string
  instance_name: string
  rank: number
}

export function fixtureModel(overrides: Partial<FixtureModel> = {}): FixtureModel {
  return {
    model_id: 'model-1',
    tenant_id: 'tenant-1',
    tenant_name: 'recorder',
    model_type: ['chat'],
    name: 'fake-chat',
    provider_id: 'provider-1',
    provider_name: 'OpenAI-API-Compatible',
    instance_id: 'instance-1',
    instance_name: 'recorder',
    rank: 500,
    ...overrides,
  }
}

/**
 * Rejestr modeli (`GET /api/v1/models`) z jawnie podanymi elementami. Domyślny handler w
 * `handlers` zwraca pustą listę — testy szuflady czatu podmieniają go przez
 * `server.use(...modelsHandlers([...]))`.
 */
export function modelsHandlers(items: FixtureModel[]): HttpHandler[] {
  return [
    http.get(apiUrl('/api/v1/models'), () =>
      HttpResponse.json({ code: 0, message: 'success', data: items }),
    ),
  ]
}

// Domyślne handlery modeli: modele bieżącego użytkownika i pusty rejestr WD.
export const modelsDefaultHandlers: HttpHandler[] = [
  http.get(apiUrl('/api/v1/users/me/models'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: fixtureModels }),
  ),

  // Rejestr modeli WD (08 §8.2) — domyślnie pusto, jak pozostałe listy; testy szuflady
  // podmieniają go przez `server.use(...modelsHandlers([...]))`.
  http.get(apiUrl('/api/v1/models'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: [] }),
  ),
]
