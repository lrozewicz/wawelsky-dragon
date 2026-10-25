import { createFileRoute } from '@tanstack/react-router'
import { zodValidator } from '@tanstack/zod-adapter'
import { z } from 'zod'

import { useOidcErrorNotice } from '../../features/auth/useOidcErrorNotice'
import { HomePage } from '../../features/home/HomePage'

// `?error=<slug>` — błąd OIDC, na który backend przekierowuje na stronę główną (08 §5.2).
export const homeSearchSchema = z.object({
  error: z.string().optional(),
})

export const Route = createFileRoute('/_app/')({
  validateSearch: zodValidator(homeSearchSchema),
  component: HomeRoute,
})

function HomeRoute() {
  const { error } = Route.useSearch()
  useOidcErrorNotice(error)

  return <HomePage />
}
