import { createFileRoute, redirect } from '@tanstack/react-router'
import { zodValidator } from '@tanstack/zod-adapter'
import { z } from 'zod'

import { LoginPage } from '../features/auth/LoginPage'
import { safeRedirect } from '../features/auth/redirect'
import { useOidcErrorNotice } from '../features/auth/useOidcErrorNotice'

// `redirect` — powrót po zalogowaniu; `error` — slug błędu OIDC z callbacku (alert rysuje T3).
export const loginSearchSchema = z.object({
  redirect: z.string().optional(),
  error: z.string().optional(),
})

export const Route = createFileRoute('/login')({
  validateSearch: zodValidator(loginSearchSchema),
  beforeLoad: async ({ context, search }) => {
    // Powrót z błędem OIDC pokazuje stronę logowania (T3 wyświetla slug) — bez pętli przekierowań.
    if (search.error !== undefined) return
    if ((await context.auth.ensureSession()) !== null) {
      throw redirect({ to: safeRedirect(search.redirect) })
    }
  },
  component: LoginRoute,
})

function LoginRoute() {
  const { auth } = Route.useRouteContext()
  const { redirect: redirectTo, error } = Route.useSearch()
  // Błąd OIDC z callbacku pokazujemy powiadomieniem (ten sam hook co na stronie głównej).
  useOidcErrorNotice(error)

  return <LoginPage auth={auth} redirectTo={redirectTo} />
}
