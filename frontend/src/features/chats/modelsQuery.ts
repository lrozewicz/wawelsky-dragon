/**
 * Lista modeli rejestru WD (`GET /api/v1/models`) dla comboboxa „Model” w ustawieniach czatu
 * (08 §8.2) — wzór z `features/models/queries.ts`: jawne `queryOptions`, koperta rozpakowana
 * przez `apiCall` (złoto system--11.json: `data` to tablica `Model`).
 */

import { queryOptions } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import type { components } from '../../api/schema.gen'

export type Model = components['schemas']['Model']

export function modelsListQueryOptions() {
  return queryOptions({
    queryKey: ['models', 'list'] as const,
    queryFn: () => apiCall<Model[]>(api.GET('/api/v1/models')),
  })
}

/** Minimalny kształt modelu z `GET /api/v1/models` potrzebny comboboxowi „Model”. */
export type ModelSummary = { model_id: string; name: string; model_type: string[] }

/** Opcja comboboxa „Model”: `id` trafia do `llm_id`, `label` jest widoczną nazwą modelu. */
export type ModelOption = { id: string; label: string }

/**
 * Opcje pola `llm_id` (08 §8.2): modele czatu z rejestru (`model_type` zawiera `'chat'`) jako
 * `{id: model_id, label: name}`. Model bieżący (models.id) i domyślny użytkownika dokładamy,
 * gdy brak ich na liście, żeby wartość pola nie zniknęła, gdy `/models` zawiedzie albo model
 * zniknął z rejestru. `users/me/models.llm_id` to NAZWA modelu, więc domyślnego nie dokładamy,
 * gdy rejestr zna już model o tej nazwie — inaczej lista pokazywałaby dwa razy tę samą nazwę
 * (raz z id, raz z nazwą jako wartością). Zapis zawsze wysyła `id`.
 * (Z `settings/schema.ts`: limit rozmiaru pliku, wzór `useSaveWithApply`.)
 */
export function buildModelOptions(
  models: readonly ModelSummary[],
  currentLlmId: string,
  defaultLlmId: string,
): ModelOption[] {
  const options: ModelOption[] = []
  const knownIds = new Set<string>()
  const knownLabels = new Set<string>()
  for (const model of models) {
    if (!model.model_type.includes('chat') || knownIds.has(model.model_id)) continue
    knownIds.add(model.model_id)
    knownLabels.add(model.name)
    options.push({ id: model.model_id, label: model.name })
  }
  if (currentLlmId !== '' && !knownIds.has(currentLlmId)) {
    knownIds.add(currentLlmId)
    options.push({ id: currentLlmId, label: currentLlmId })
  }
  if (defaultLlmId !== '' && !knownIds.has(defaultLlmId) && !knownLabels.has(defaultLlmId)) {
    options.push({ id: defaultLlmId, label: defaultLlmId })
  }
  return options
}
