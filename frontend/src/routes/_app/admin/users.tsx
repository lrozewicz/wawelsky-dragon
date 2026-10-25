import { Suspense, lazy } from 'react'
import type { JSX } from 'react'
import Skeleton from '@mui/material/Skeleton'
import { createFileRoute } from '@tanstack/react-router'

import { AdminLayout } from '../../../features/admin/AdminLayout'

// Strona ciągnie `@mui/x-data-grid` — ładujemy ją leniwie (wzór: `dataset/logs.$id.tsx`).
const UsersPage = lazy(async () => {
  const module = await import('../../../features/admin/users/UsersPage')
  return { default: module.UsersPage }
})

export const Route = createFileRoute('/_app/admin/users')({
  component: AdminUsersRoute,
})

function AdminUsersRoute(): JSX.Element {
  return (
    <AdminLayout active="users" showIntegrations>
      <Suspense fallback={<Skeleton variant="rounded" height={420} />}>
        <UsersPage />
      </Suspense>
    </AdminLayout>
  )
}
