import { Outlet, createFileRoute } from '@tanstack/react-router'

import { requireSuperuser } from '../../../app/guards'

// Sekcja administracyjna — dostęp tylko dla superusera (08 §5.3). Strony dojdą w E5.
export const Route = createFileRoute('/_app/admin')({
  beforeLoad: ({ context }) => requireSuperuser(context.auth),
  component: () => <Outlet />,
})
