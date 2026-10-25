import { createFileRoute } from '@tanstack/react-router'

import { AdminLayout } from '../../../features/admin/AdminLayout'
import { AccessPage } from '../../../features/admin/access/AccessPage'

export const Route = createFileRoute('/_app/admin/access')({
  component: AdminAccessRoute,
})

function AdminAccessRoute() {
  return (
    <AdminLayout active="access" showIntegrations>
      <AccessPage />
    </AdminLayout>
  )
}
