import { createFileRoute } from '@tanstack/react-router'

import { AdminLayout } from '../../../features/admin/AdminLayout'
import { StatusPage } from '../../../features/admin/status/StatusPage'

export const Route = createFileRoute('/_app/admin/status')({
  component: AdminStatusRoute,
})

function AdminStatusRoute() {
  return (
    <AdminLayout active="status" showIntegrations>
      <StatusPage />
    </AdminLayout>
  )
}
