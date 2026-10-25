/**
 * Flaga superusera z kontekstu trasy `/_app` (kontrakt WP E3-6c1 §0) — wzór:
 * `features/admin/users/UsersPage.tsx`. Steruje widocznością przycisków zapisu w Ustawieniach.
 */

import { useRouteContext } from '@tanstack/react-router'

export function useIsSuperuser(): boolean {
  return useRouteContext({
    from: '/_app',
    select: (context) => context.auth?.user?.is_superuser ?? false,
  })
}
