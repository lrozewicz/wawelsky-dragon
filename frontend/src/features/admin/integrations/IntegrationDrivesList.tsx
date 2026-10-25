/**
 * Biblioteki integracji (brief T4 p. 4): nazwa, kursor delty i czas ostatniej synchronizacji.
 * Zanim przebieg odkryje biblioteki, lista jest pusta — wtedy pokazujemy zachętę do
 * synchronizacji, a błąd (np. 502 z Graph) dostaje `Alert` z kluczem z `wdErrorKey`.
 */

import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { wdErrorKey } from '../wdClient'

import { integrationDrivesQueryOptions } from './queries'
import type { IntegrationDrive } from './queries'

export type IntegrationDrivesListProps = { integrationId: number }

/** Czas jak w kontrakcie §0: ISO albo „—”, gdy brak wartości. */
function formatTime(value: string | null, language: string): string {
  return value === null ? '—' : new Date(value).toLocaleString(language)
}

function DriveRow(props: { drive: IntegrationDrive; language: string }): JSX.Element {
  const { drive, language } = props
  const { t } = useTranslation()
  const lastSync = `${t('integrations.details.drives.lastSync')}: ${formatTime(drive.last_sync_at, language)}`

  return (
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
      <Typography sx={{ flexGrow: 1 }}>{drive.drive_name}</Typography>
      {drive.has_delta ? (
        <Chip size="small" color="info" label={t('integrations.details.drives.delta')} />
      ) : null}
      <Typography variant="body2" color="text.secondary">
        {lastSync}
      </Typography>
    </Stack>
  )
}

export function IntegrationDrivesList(props: IntegrationDrivesListProps): JSX.Element {
  const { integrationId } = props
  const { t, i18n } = useTranslation()
  const drives = useQuery(integrationDrivesQueryOptions(integrationId))

  if (drives.isError) {
    return <Alert severity="error">{t(wdErrorKey(drives.error))}</Alert>
  }
  if (drives.isPending) {
    return <CircularProgress size={20} />
  }

  const rows = drives.data
  if (rows.length === 0) {
    return <Typography color="text.secondary">{t('integrations.details.drives.empty')}</Typography>
  }

  return (
    <Stack spacing={1}>
      {rows.map((drive) => (
        <DriveRow key={drive.drive_id} drive={drive} language={i18n.language} />
      ))}
    </Stack>
  )
}
