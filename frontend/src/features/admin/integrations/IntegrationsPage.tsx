/**
 * Zakładka Admin → Integracje (kontrakt WP E4-3c §1 i §T2 pkt 1–3): lista integracji SharePoint
 * z przyciskiem dodawania oraz dialogami formularza i szczegółów. Stany listy rozstrzygamy
 * po kolei: błąd (`Alert` z kluczem z `wdErrorKey`), ładowanie, pusty stan i siatka.
 * Stan trzymamy tu, bo dialogi są stubami do czasu T3/T4 — propsy to zamrożony kontrakt.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../../../components/EmptyState'
import { QueryError } from '../../../components/QueryError'
import { wdErrorKey } from '../wdClient'

import { IntegrationDetailsDialog } from './IntegrationDetailsDialog'
import { IntegrationFormDialog } from './IntegrationFormDialog'
import { IntegrationsGrid } from './IntegrationsGrid'
import { integrationsListQueryOptions } from './queries'
import type { Integration } from './queries'

/** Cel formularza: tworzenie nowej integracji albo edycja istniejącej (kontrakt §1). */
type FormTarget = { mode: 'create' } | { mode: 'edit'; integration: Integration }

export function IntegrationsPage(): JSX.Element {
  const { t } = useTranslation()
  const list = useQuery(integrationsListQueryOptions())
  const [formTarget, setFormTarget] = useState<FormTarget | null>(null)
  const [detailsId, setDetailsId] = useState<number | null>(null)

  const rows = list.data ?? []

  let content: JSX.Element
  if (list.isError) {
    // Kontrakt WP E3-7 §C6: błąd zapytania to `QueryError` z ponowieniem, nie ad-hoc `Alert`.
    content = <QueryError message={t(wdErrorKey(list.error))} onRetry={() => void list.refetch()} />
  } else if (list.isPending) {
    content = <CircularProgress />
  } else if (rows.length === 0) {
    content = (
      <EmptyState
        title={t('integrations.list.empty.title')}
        description={t('integrations.list.empty.description')}
      />
    )
  } else {
    content = (
      <IntegrationsGrid
        rows={rows}
        onOpen={setDetailsId}
        onEdit={(integration) => setFormTarget({ mode: 'edit', integration })}
      />
    )
  }

  return (
    <Stack spacing={2} data-testid="admin-integrations">
      <Stack direction="row" spacing={2} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 2 }}>
        <Typography variant="h6" component="h2" sx={{ flexGrow: 1 }}>
          {t('integrations.title')}
        </Typography>
        <Button
          variant="contained"
          data-testid="integration-add"
          onClick={() => setFormTarget({ mode: 'create' })}
        >
          {t('integrations.add')}
        </Button>
      </Stack>

      {content}

      <IntegrationFormDialog
        open={formTarget !== null}
        integration={formTarget?.mode === 'edit' ? formTarget.integration : null}
        onClose={() => setFormTarget(null)}
      />

      <IntegrationDetailsDialog
        integrationId={detailsId}
        onClose={() => setDetailsId(null)}
        // Edycja ze szczegółów zamyka szczegóły i otwiera formularz (§T2 pkt 3).
        onEdit={(integration) => {
          setDetailsId(null)
          setFormTarget({ mode: 'edit', integration })
        }}
      />
    </Stack>
  )
}
