/**
 * Globalny router aplikacji (08 §5.3): drzewo tras z kontekstem `{auth, queryClient}`.
 * `auth` powstaje tutaj, bo jego `invalidate` musi unieważnić właśnie ten router.
 */

import { createRouter } from '@tanstack/react-router'

import { createAuthState } from '../features/auth/authState'
import { routeTree } from '../routeTree.gen'

import { queryClient } from './queryClient'

export const auth = createAuthState({
  queryClient,
  invalidate: () => router.invalidate(),
})

export const router = createRouter({
  routeTree,
  context: { auth, queryClient },
  defaultPreload: 'intent',
})

// Typy tras i nawigacji korzystają z tego routera (przeniesione z `main.tsx`).
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
