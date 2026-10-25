/**
 * Hook pytań pokrewnych (kontrakt WP E4-4b §3): `POST /api/v1/chat/recommendation` z
 * `{ question, search_id }`. Błąd lub odmowa modelu to pusta lista — UI nie ma prawa paść
 * z powodu rekomendacji.
 */

import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api, apiCall } from '../../../api/client'

export function useRelatedQuestions(
  searchId: string,
  question: string | null,
  enabled: boolean,
): UseQueryResult<string[]> {
  return useQuery({
    queryKey: ['searches', 'related', searchId, question],
    enabled: enabled && question !== null,
    queryFn: () =>
      apiCall<string[]>(
        api.POST('/api/v1/chat/recommendation', {
          body: { question: question!, search_id: searchId },
        }),
      ).catch(() => [] as string[]),
  })
}
