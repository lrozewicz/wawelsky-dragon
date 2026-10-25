/**
 * Publiczne zapytania strony logowania (08 §7.1): kanały OIDC i flagi instancji.
 * Oba endpointy są dostępne bez sesji, więc nie wymagają guardu.
 */

import { queryOptions, useQuery } from '@tanstack/react-query'

import { api, apiCall } from '../../api/client'
import type { components } from '../../api/schema.gen'

export type LoginChannel = components['schemas']['LoginChannel']
export type SystemConfig = components['schemas']['SystemConfig']

export function loginChannelsQueryOptions() {
  return queryOptions({
    queryKey: ['auth', 'login-channels'],
    queryFn: () => apiCall<LoginChannel[]>(api.GET('/api/v1/auth/login/channels')),
  })
}

/**
 * Kanały logowania OIDC. Ładowanie i błąd dają pustą listę — sekcja kanałów (z `Divider`)
 * pojawia się wyłącznie wtedy, gdy instancja faktycznie wystawia kanał (CONTRACT §Kanały).
 */
export function useLoginChannels(): LoginChannel[] {
  return useQuery(loginChannelsQueryOptions()).data ?? []
}

export function systemConfigQueryOptions() {
  return queryOptions({
    queryKey: ['system', 'config'],
    queryFn: () => apiCall<SystemConfig>(api.GET('/api/v1/system/config')),
  })
}

/** Flagi instancji: `registerEnabled` (0/1) i `disablePasswordLogin`; `undefined` przed odpowiedzią. */
export function useSystemConfig(): SystemConfig | undefined {
  return useQuery(systemConfigQueryOptions()).data
}
