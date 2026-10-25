/**
 * Dialog szczegółów integracji (kontrakt WP E4-3c §1, brief T4): stan z licznikami i pollingiem,
 * synchronizacja i anulowanie z potwierdzeniem, biblioteki, historia przebiegów ze zdarzeniami
 * oraz usunięcie z potwierdzeniem. Treść istnieje tylko dla niepustego `integrationId` i jest
 * kluczowana po integracji — zamknięcie odmontowuje stan mutacji.
 * `integrationId === null` znaczy „zamknięty”.
 */

import { useEffect, useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import FormControlLabel from '@mui/material/FormControlLabel'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ConfirmDialog } from '../../../components/ConfirmDialog'
import { useFullScreenDialog } from '../../../components/useFullScreenDialog'

import { wdErrorKey } from '../wdClient'

import { IntegrationDrivesList } from './IntegrationDrivesList'
import { RunsList } from './RunsList'
import { StatusChip } from './StatusChip'
import {
  integrationQueryOptions,
  integrationStatusQueryOptions,
  isActiveRunStatus,
  useCancelIntegration,
  useDeleteIntegration,
  useSyncIntegration,
} from './queries'
import type { Integration, IntegrationStatus } from './queries'

export type IntegrationDetailsDialogProps = {
  integrationId: number | null
  onClose: () => void
  onEdit: (integration: Integration) => void
}

/** Prefiks kluczy zdarzeń (`queries.ts` go nie eksportuje) — unieważniamy całą rodzinę przebiegów. */
const EVENTS_KEY = ['admin', 'integrations', 'events'] as const

type ConfirmKind = 'sync' | 'cancel' | 'delete'

function formatTime(value: string | null, language: string): string {
  return value === null ? '—' : new Date(value).toLocaleString(language)
}

export function IntegrationDetailsDialog(props: IntegrationDetailsDialogProps): JSX.Element {
  const { integrationId, onClose, onEdit } = props
  // Poniżej `sm` (m.in. 390 px) dialog zajmuje cały ekran, jak pozostałe widoki mobilne.
  const belowSm = useFullScreenDialog()

  return (
    <Dialog
      open={integrationId !== null}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      fullScreen={belowSm}
      data-testid="integration-details"
    >
      {integrationId === null ? null : (
        <DetailsBody
          key={integrationId}
          integrationId={integrationId}
          onClose={onClose}
          onEdit={onEdit}
        />
      )}
    </Dialog>
  )
}

type DetailsBodyProps = {
  integrationId: number
  onClose: () => void
  onEdit: (integration: Integration) => void
}

function DetailsBody(props: DetailsBodyProps): JSX.Element {
  const { integrationId, onClose, onEdit } = props
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [deleted, setDeleted] = useState(false)
  // Po usunięciu wyłączamy zapytania zasobu, zanim jeszcze zamkniemy dialog — inaczej React Query
  // dociąga trasy usuniętej integracji (404 w konsoli, WNIOSEK E4-3d).
  const detail = useQuery({ ...integrationQueryOptions(integrationId), enabled: !deleted })
  const status = useQuery({ ...integrationStatusQueryOptions(integrationId), enabled: !deleted })
  const sync = useSyncIntegration(integrationId)
  const cancel = useCancelIntegration(integrationId)
  const remove = useDeleteIntegration()
  const [confirm, setConfirm] = useState<ConfirmKind | null>(null)
  const [full, setFull] = useState(false)

  const latest: IntegrationStatus['latest_run'] = status.data?.latest_run ?? null
  const active = status.data !== undefined && isActiveRunStatus(status.data)
  const mutationError = sync.error ?? cancel.error ?? remove.error
  // Zmiana stanu przebiegu unieważnia listę zdarzeń — bez własnego timera (brief p. 6).
  const runSignature =
    latest === null
      ? 'none'
      : `${latest.id}:${latest.status}:${latest.added}:${latest.updated}:${latest.deleted}:${latest.failed}`

  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: EVENTS_KEY })
  }, [queryClient, runSignature])

  function edit(): void {
    if (detail.data !== undefined) onEdit(detail.data)
  }

  /** Potwierdzenia zamykamy po rozstrzygnięciu mutacji — błąd pokazuje `Alert` w dialogu. */
  function runSync(): void {
    sync.mutate({ full }, { onSettled: () => setConfirm(null) })
  }

  function runCancel(): void {
    cancel.mutate(undefined, { onSettled: () => setConfirm(null) })
  }

  function runDelete(): void {
    // Gasimy zapytania zasobu jeszcze przed mutacją; nieudane usunięcie je przywraca (onError).
    setDeleted(true)
    remove.mutate(integrationId, {
      onSuccess: onClose,
      onError: () => setDeleted(false),
      onSettled: () => setConfirm(null),
    })
  }

  return (
    <>
      <DialogTitle>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <Typography variant="h6" component="span" sx={{ flexGrow: 1 }}>
            {detail.data?.name ?? t('integrations.details.title')}
          </Typography>
          <Button size="small" disabled={detail.data === undefined} onClick={edit}>
            {t('integrations.details.edit')}
          </Button>
        </Stack>
      </DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {detail.isError ? <Alert severity="error">{t(wdErrorKey(detail.error))}</Alert> : null}
          {status.isError ? <Alert severity="error">{t(wdErrorKey(status.error))}</Alert> : null}
          {mutationError === null ? null : (
            <Alert severity="error">{t(wdErrorKey(mutationError))}</Alert>
          )}

          <Stack spacing={1}>
            <Typography variant="subtitle2">{t('integrations.details.state')}</Typography>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <StatusChip status={latest?.status ?? status.data?.last_sync_status ?? null} />
            </Stack>
            {latest === null ? null : (
              <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                <Typography variant="body2">
                  {`${t('integrations.details.started')}: ${formatTime(latest.started_at, i18n.language)}`}
                </Typography>
                <Typography variant="body2">
                  {`${t('integrations.details.finished')}: ${formatTime(latest.finished_at, i18n.language)}`}
                </Typography>
                <Typography variant="body2">
                  {`${t('integrations.details.counts.added')}: ${latest.added}`}
                </Typography>
                <Typography variant="body2">
                  {`${t('integrations.details.counts.updated')}: ${latest.updated}`}
                </Typography>
                <Typography variant="body2">
                  {`${t('integrations.details.counts.deleted')}: ${latest.deleted}`}
                </Typography>
                <Typography variant="body2">
                  {`${t('integrations.details.counts.failed')}: ${latest.failed}`}
                </Typography>
              </Stack>
            )}
            {status.data?.is_running === true ? <LinearProgress /> : null}
          </Stack>

          <Stack spacing={1}>
            <Typography variant="subtitle2">{t('integrations.details.drives.title')}</Typography>
            <IntegrationDrivesList integrationId={integrationId} />
          </Stack>

          <RunsList integrationId={integrationId} />
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button data-testid="integration-sync" disabled={active} onClick={() => setConfirm('sync')}>
          {t('integrations.details.sync')}
        </Button>
        {active ? (
          <Button data-testid="integration-cancel" onClick={() => setConfirm('cancel')}>
            {t('integrations.details.cancel')}
          </Button>
        ) : null}
        <Button color="error" data-testid="integration-delete" onClick={() => setConfirm('delete')}>
          {t('integrations.details.delete')}
        </Button>
        <Button onClick={onClose}>{t('integrations.details.close')}</Button>
      </DialogActions>

      <ConfirmDialog
        open={confirm === 'sync'}
        title={t('integrations.details.syncConfirm.title')}
        message={t('integrations.details.syncConfirm.body')}
        confirmLabel={t('integrations.details.sync')}
        cancelLabel={t('integrations.details.close')}
        loading={sync.isPending}
        onConfirm={runSync}
        onCancel={() => setConfirm(null)}
      >
        <FormControlLabel
          control={<Checkbox checked={full} onChange={(event) => setFull(event.target.checked)} />}
          label={t('integrations.details.syncFull')}
        />
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === 'cancel'}
        title={t('integrations.details.cancelConfirm.title')}
        message={t('integrations.details.cancelConfirm.body')}
        confirmLabel={t('integrations.details.cancel')}
        cancelLabel={t('integrations.details.close')}
        loading={cancel.isPending}
        onConfirm={runCancel}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === 'delete'}
        title={t('integrations.details.deleteConfirm.title')}
        message={t('integrations.details.deleteConfirm.body')}
        confirmLabel={t('integrations.details.delete')}
        cancelLabel={t('integrations.details.close')}
        loading={remove.isPending}
        onConfirm={runDelete}
        onCancel={() => setConfirm(null)}
      />
    </>
  )
}
