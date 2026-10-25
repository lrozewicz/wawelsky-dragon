/**
 * Status systemu (kontrakt WP E3-6c2 §4): karty „Baza danych”, „Magazyn plików”, „Workery”,
 * „Kolejka” i „Wersja”. Dane idą z `statsQueryOptions` (odświeżanie 10 s), a chip stanu
 * wersji z `healthzQueryOptions`. Awaria jednego zapytania nie gasi kart drugiego, a błąd
 * statsów pokazuje się osobno w każdej karcie, która z nich korzysta.
 */

import type { JSX } from 'react'
import Chip from '@mui/material/Chip'
import Grid from '@mui/material/Grid'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { healthzQueryOptions, statsQueryOptions } from '../queries'
import type { Stats } from '../queries'

import { StatusCard } from './StatusCard'

/** Ostatni sygnał workera: ISO 8601 → data w języku interfejsu; brak sygnału to kreska. */
function formatHeartbeat(value: string | null, language: string): string {
  return value === null ? '—' : new Date(value).toLocaleString(language)
}

/** Karta sondy (baza danych / magazyn plików): chip OK/Błąd i czas trwania sondy. */
function ProbeCard(props: {
  testId: string
  title: string
  probe: Stats['database'] | undefined
  isLoading: boolean
  isError: boolean
}): JSX.Element {
  const { t } = useTranslation()

  return (
    <StatusCard
      testId={props.testId}
      title={props.title}
      isLoading={props.isLoading}
      isError={props.isError}
    >
      {props.probe ? (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <Chip
            color={props.probe.ok ? 'success' : 'error'}
            label={props.probe.ok ? t('admin.status.ok') : t('admin.status.fail')}
          />
          <Typography variant="body2" color="text.secondary">
            {t('admin.status.elapsed', { ms: Math.round(props.probe.elapsed_ms) })}
          </Typography>
        </Stack>
      ) : null}
    </StatusCard>
  )
}

export function StatusPage(): JSX.Element {
  const { t, i18n } = useTranslation()

  const stats = useQuery(statsQueryOptions())
  const healthz = useQuery(healthzQueryOptions())

  const workers = stats.data?.workers
  const queue = stats.data?.queue
  // Wiersze kolejki liczone tylko z pobranych statsów — brak danych = karta pusta.
  const queueRows = queue
    ? [
        { id: 'queued', label: t('admin.status.queued'), value: queue.queued },
        { id: 'running', label: t('admin.status.running'), value: queue.running },
        { id: 'dead', label: t('admin.status.dead'), value: queue.dead },
      ]
    : []

  return (
    <Stack spacing={3} data-testid="admin-status">
      {/* Nagłówek `h1` („Administracja”) należy do `AdminLayout` (T2) — tu tylko karty. */}
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 6, lg: 4 }}>
          <ProbeCard
            testId="admin-status-db"
            title={t('admin.status.db')}
            probe={stats.data?.database}
            isLoading={stats.isLoading}
            isError={stats.isError}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 6, lg: 4 }}>
          <ProbeCard
            testId="admin-status-storage"
            title={t('admin.status.storage')}
            probe={stats.data?.storage}
            isLoading={stats.isLoading}
            isError={stats.isError}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 6, lg: 4 }}>
          <StatusCard
            testId="admin-status-workers"
            title={t('admin.status.workers')}
            isLoading={stats.isLoading}
            isError={stats.isError}
          >
            {workers ? (
              <Stack spacing={1.5}>
                <Typography variant="body1">
                  {t('admin.status.activeWorkers', { count: workers.active })}
                </Typography>
                {workers.items.map((worker) => (
                  <Stack key={worker.worker_id} spacing={0.25}>
                    <Typography variant="body2">{worker.worker_id}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {worker.version ?? '—'}
                    </Typography>
                    {/* „Ostatni sygnał” (SC-E5-H9-05): podpowiedź tłumaczy źródło wartości. */}
                    <Tooltip title={t('admin.status.lastSignalHint')}>
                      <Typography variant="caption" color="text.secondary">
                        {t('admin.status.lastSignal', {
                          at: formatHeartbeat(worker.heartbeat_at, i18n.language),
                        })}
                      </Typography>
                    </Tooltip>
                  </Stack>
                ))}
              </Stack>
            ) : null}
          </StatusCard>
        </Grid>
        <Grid size={{ xs: 12, md: 6, lg: 4 }}>
          <StatusCard
            testId="admin-status-queue"
            title={t('admin.status.queue')}
            isLoading={stats.isLoading}
            isError={stats.isError}
          >
            {queue ? (
              <Stack spacing={1}>
                {queueRows.map((row) => (
                  <Stack key={row.id} direction="row" sx={{ justifyContent: 'space-between' }}>
                    <Typography variant="body2" color="text.secondary">
                      {row.label}
                    </Typography>
                    <Typography variant="h6">{row.value}</Typography>
                  </Stack>
                ))}
              </Stack>
            ) : null}
          </StatusCard>
        </Grid>
        <Grid size={{ xs: 12, md: 6, lg: 4 }}>
          {/* Karta wersji korzysta z obu zapytań: błąd tylko gdy padły oba (kontrakt §T6 p. 5). */}
          <StatusCard
            testId="admin-status-version"
            title={t('admin.status.version')}
            isLoading={stats.isLoading || healthz.isLoading}
            isError={stats.isError && healthz.isError}
          >
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <Typography variant="body1">{stats.data?.version ?? '—'}</Typography>
              {healthz.data ? (
                <Chip
                  color={healthz.data.status === 'ok' ? 'success' : 'error'}
                  label={healthz.data.status}
                />
              ) : null}
            </Stack>
          </StatusCard>
        </Grid>
      </Grid>
    </Stack>
  )
}
