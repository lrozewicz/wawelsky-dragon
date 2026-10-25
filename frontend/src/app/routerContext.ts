/**
 * Kontekst routera (08 §5.3) w osobnym module bez zależności od `router.tsx`, żeby trasy
 * mogły go zaimportować, nie tworząc cyklu importów (`router.tsx` → `routeTree.gen` → trasy).
 */

import type { QueryClient } from '@tanstack/react-query'

import type { AuthState } from '../features/auth/authState'

export type RouterContext = {
  auth: AuthState
  queryClient: QueryClient
}
