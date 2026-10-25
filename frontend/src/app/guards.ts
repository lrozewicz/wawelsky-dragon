/**
 * Czyste guardy tras (08 §5.3) — używane w `beforeLoad`. Bez zależności od routera, więc
 * dają się testować jednostkowo (100% gałęzi).
 */

import { redirect } from '@tanstack/react-router'

import type { AuthState } from '../features/auth/authState'

/** Brak sesji → przekierowanie na `/login` z powrotem do bieżącego adresu. */
export async function requireSession(
  auth: Pick<AuthState, 'ensureSession'>,
  location: { href: string },
): Promise<void> {
  const session = await auth.ensureSession()
  if (session === null) {
    throw redirect({ to: '/login', search: { redirect: location.href } })
  }
}

/** Brak superusera → przekierowanie na stronę główną. */
export function requireSuperuser(auth: Pick<AuthState, 'user'>): void {
  if (!auth.user?.is_superuser) {
    throw redirect({ to: '/' })
  }
}
