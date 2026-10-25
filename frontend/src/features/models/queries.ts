/**
 * Domyślne modele instancji (08 §4.3, §9.2): alert w SideMenu pojawia się, gdy brak LLM
 * albo embeddingu. Ładowanie i błąd nie pokazują alertu.
 */

import { queryOptions, useQuery } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import type { components } from '../../api/schema.gen'

export type DefaultModels =
  components['schemas']['app__api__ragflow__schemas__users__DefaultModels']

export function modelsQueryOptions() {
  return queryOptions({
    queryKey: ['models', 'me'],
    queryFn: () => apiCall<DefaultModels>(api.GET('/api/v1/users/me/models')),
  })
}

/** Oba domyślne modele muszą być niepuste (pusty string = brak, CONTRACT §Modele). */
export function hasDefaultModels(models: DefaultModels): boolean {
  return models.llm_id !== '' && models.embd_id !== ''
}

/** `false` dopóki dane się ładują lub wystąpił błąd; `true`, gdy brakuje modelu. */
export function useShowModelsAlert(): boolean {
  const { data } = useQuery(modelsQueryOptions())
  return data === undefined ? false : !hasDefaultModels(data)
}
