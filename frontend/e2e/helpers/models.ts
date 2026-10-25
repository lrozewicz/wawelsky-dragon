// Pomocniki API scenariuszy S17 (WP E5-H8c T1): instancja dostawcy z modelami utworzona przez
// API (kontrakt WP E5-H8c §1: „instancję z 3 modelami utwórz przez API") i odczyt modeli
// `GET …/models` dla kroku „inne klucze `extra` zachowane". Koperta RAGFlow (HTTP 200 + `code 0`)
// jak w `e2e/helpers.ts`; sprzątanie przez DELETE instancji.
import type { APIRequestContext, APIResponse } from '@playwright/test'

import { expect } from '../fixtures'

const API_URL = process.env.WD_E2E_API_URL ?? ''

type Envelope<T> = { code: number; message: string; data: T }

/** Rozwija kopertę RAGFlow: HTTP 200 + `code 0`, inaczej `expect` rzuca z opisem trasy. */
async function ok<T>(pending: Promise<APIResponse>, label: string): Promise<T> {
  const response = await pending
  const body = (await response.json()) as Envelope<T>
  expect(response.status(), `${label}: HTTP ${response.status()} — ${body.message}`).toBe(200)
  expect(body.code, `${label}: ${body.message}`).toBe(0)
  return body.data
}

/** Typ modelu przy tworzeniu (K13 §2: `vision` trafia do kolumny `image2text`). */
export type InstanceModelType = 'chat' | 'embedding' | 'rerank' | 'vision'

/** Specyfikacja modelu do zasiania w nowej instancji (`extra` — np. `max_concurrency`). */
export type InstanceModelSpec = {
  name: string
  modelType: InstanceModelType
  maxTokens?: number
  extra?: Record<string, unknown>
}

/** Model instancji z `GET …/models` (K13 §3); `extra` potrzebne asercjom zachowania kluczy. */
export type InstanceModel = {
  name: string
  model_type: string
  max_tokens: number | null
  status: string
  extra: Record<string, unknown>
}

/** Base URL instancji — ten sam co `WD_LLM_BASE_URL` stosu testowego (fake-llm). */
const INSTANCE_BASE_URL = 'http://fake-llm:8090/v1'

/**
 * Tworzy instancję dostawcy i zasiewa jej modele (POST …/instances + POST …/models).
 * Nazwy modeli muszą być unikalne w rejestrze tenantu (duplikat → 102, K13 §4), więc
 * scenariusze przekazują nazwy z sufiksem. Zwraca id instancji (ścieżka `{instance}`).
 */
export async function createInstanceWithModels(
  request: APIRequestContext,
  token: string,
  instanceName: string,
  models: InstanceModelSpec[],
): Promise<string> {
  const headers = { authorization: `Bearer ${token}` }
  // POST …/instances zwraca kopertę bez ciała (RagflowOkEmpty) — id bierzemy z listy instancji
  // (`default` pierwsza, potem wiersze tabeli; K13 §3 p. 1).
  await ok<unknown>(
    request.post(`${API_URL}/api/v1/providers/litellm/instances`, {
      headers,
      data: { instance_name: instanceName, base_url: INSTANCE_BASE_URL },
    }),
    'POST /api/v1/providers/litellm/instances',
  )
  const instances = await ok<{ id: string; instance_name: string }[]>(
    request.get(`${API_URL}/api/v1/providers/litellm/instances`, { headers }),
    'GET /api/v1/providers/litellm/instances',
  )
  const instance = instances.find((entry) => entry.instance_name === instanceName)
  expect(instance, `instancja „${instanceName}” na liście po utworzeniu`).toBeDefined()
  for (const model of models) {
    await ok<unknown>(
      request.post(`${API_URL}/api/v1/providers/litellm/instances/${instance!.id}/models`, {
        headers,
        data: {
          model_name: model.name,
          model_type: model.modelType,
          ...(model.maxTokens === undefined ? {} : { max_tokens: model.maxTokens }),
          ...(model.extra === undefined ? {} : { extra: model.extra }),
        },
      }),
      `POST …/instances/{id}/models (${model.name})`,
    )
  }
  return instance!.id
}

/** Lista instancji dostawcy — `default` jest pierwsza (K13 §3 p. 1). */
export async function listInstances(
  request: APIRequestContext,
  token: string,
): Promise<{ id: string; instance_name: string }[]> {
  return ok<{ id: string; instance_name: string }[]>(
    request.get(`${API_URL}/api/v1/providers/litellm/instances`, {
      headers: { authorization: `Bearer ${token}` },
    }),
    'GET /api/v1/providers/litellm/instances',
  )
}

/** Zmienia model instancji (`PATCH …/models/{name}`) — np. sprzątanie `extra` po teście. */
export async function patchInstanceModel(
  request: APIRequestContext,
  token: string,
  instanceId: string,
  modelName: string,
  body: Record<string, unknown>,
): Promise<void> {
  await ok<unknown>(
    request.patch(
      `${API_URL}/api/v1/providers/litellm/instances/${instanceId}/models/${modelName}`,
      {
        headers: { authorization: `Bearer ${token}` },
        data: body,
      },
    ),
    `PATCH …/instances/{id}/models/${modelName}`,
  )
}

/** Lista modeli instancji — `GET …/models` (krok „inne klucze `extra` zachowane", SC-E5-H8c-04). */
export async function getInstanceModels(
  request: APIRequestContext,
  token: string,
  instanceId: string,
): Promise<InstanceModel[]> {
  return ok<InstanceModel[]>(
    request.get(`${API_URL}/api/v1/providers/litellm/instances/${instanceId}/models`, {
      headers: { authorization: `Bearer ${token}` },
    }),
    'GET /api/v1/providers/litellm/instances/{id}/models',
  )
}

/** Usuwa instancję (z jej modelami) — sprzątanie po scenariuszu. */
export async function deleteInstance(
  request: APIRequestContext,
  token: string,
  instanceId: string,
): Promise<void> {
  await ok<unknown>(
    request.delete(`${API_URL}/api/v1/providers/litellm/instances`, {
      headers: { authorization: `Bearer ${token}` },
      data: { instances: [instanceId] },
    }),
    'DELETE /api/v1/providers/litellm/instances',
  )
}

/** Ustawia język profilu admina (`PATCH /users/me`) — wariant EN: profil nadpisuje locale. */
export async function setProfileLanguage(
  request: APIRequestContext,
  token: string,
  language: 'pl' | 'en',
): Promise<void> {
  await ok<unknown>(
    request.patch(`${API_URL}/api/v1/users/me`, {
      headers: { authorization: `Bearer ${token}` },
      data: { language },
    }),
    'PATCH /api/v1/users/me',
  )
}
