import { createFileRoute } from '@tanstack/react-router'

import { AdminLayout } from '../../../features/admin/AdminLayout'
import { IntegrationsPage } from '../../../features/admin/integrations/IntegrationsPage'

// Zakładka Admin → Integracje (kontrakt WP E4-3c §4): treść daje `IntegrationsPage`.
export const Route = createFileRoute('/_app/admin/integrations')({
  component: AdminIntegrationsRoute,
})

function AdminIntegrationsRoute() {
  return (
    <AdminLayout active="integrations" showIntegrations>
      <IntegrationsPage />
    </AdminLayout>
  )
}
