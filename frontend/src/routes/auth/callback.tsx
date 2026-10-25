import { createFileRoute, redirect } from '@tanstack/react-router'
import { zodValidator } from '@tanstack/zod-adapter'
import { z } from 'zod'

import { CallbackPage } from '../../features/auth/CallbackPage'
import { safeRedirect } from '../../features/auth/redirect'

// `redirect` — cel po zalogowaniu (tylko ścieżka wewnętrzna); `error` — slug błędu OIDC.
export const callbackSearchSchema = z.object({
  redirect: z.string().optional(),
  error: z.string().optional(),
})

export const Route = createFileRoute('/auth/callback')({
  validateSearch: zodValidator(callbackSearchSchema),
  beforeLoad: async ({ context, search }) => {
    // Błąd dostawcy tożsamości (backend robi 302 na `?error=<slug>`) — pokaże go ekran logowania.
    if (search.error !== undefined) {
      throw redirect({ to: '/login', search: { error: search.error } })
    }
    // Cookie `wd_refresh` ustawia backend przed przekierowaniem tutaj (08 §5.2).
    if ((await context.auth.ensureSession()) === null) {
      throw redirect({ to: '/login' })
    }
    throw redirect({ to: safeRedirect(search.redirect) })
  },
  component: CallbackPage,
})
