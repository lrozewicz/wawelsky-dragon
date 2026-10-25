/**
 * Zakładka „Logi” szczegółów datasetu (kontrakt WP E3-3a §T5): 4 karty statystyk
 * (`ingestions/summary`), filtr statusu i tabela zadań (`DataGrid` z paginacją serwerową
 * 10/25/50) oraz dialog logu. Ciężką siatkę ładuje leniwie trasa `/_app/dataset/logs/$id`.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import ArticleOutlinedIcon from '@mui/icons-material/ArticleOutlined'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Grid from '@mui/material/Grid'
import IconButton from '@mui/material/IconButton'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { DataGrid } from '@mui/x-data-grid'
import type { GridColDef, GridPaginationModel } from '@mui/x-data-grid'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../../../components/EmptyState'
import { QueryError } from '../../../components/QueryError'
import { useDataGridLocaleText } from '../../../hooks/useDataGridLocaleText'
import { resolveLanguage } from '../../../i18n'
import { formatNumber } from '../../../lib/format'
import { ingestionLogsQueryOptions, ingestionSummaryQueryOptions } from '../queries'
import type { IngestionLog } from '../queries'

import { IngestionLogDialog, IngestionStatusChip } from './IngestionLogDialog'

/** Kody `run` z kontraktu §Fakty API — kolejność opcji filtra statusu. */
const STATUS_CODES = [0, 1, 2, 3, 4, 5] as const

/** Rozmiary stron siatki (kontrakt §T5). */
const PAGE_SIZE_OPTIONS = [10, 25, 50]

/** Wysokość siatki — jsdom nie mierzy kontenera, a `disableVirtualization` i tak renderuje wiersze. */
const GRID_HEIGHT = 420

function NoRowsOverlay(): JSX.Element {
  const { t } = useTranslation()

  return <EmptyState title={t('datasets.logs.empty')} />
}

/** Karta statystyki podsumowania; brak danych (ładowanie/błąd) pokazuje kreskę. */
function StatCard(props: { id: string; label: string; value?: number }): JSX.Element {
  const { i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)

  return (
    <Card data-testid={`logs-stat-${props.id}`} sx={{ height: '100%' }}>
      <CardContent>
        <Stack spacing={0.5}>
          <Typography variant="body2" color="text.secondary">
            {props.label}
          </Typography>
          <Typography variant="h5">
            {props.value === undefined ? '—' : formatNumber(props.value, language)}
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  )
}

export type LogsTabProps = {
  datasetId: string
}

export function LogsTab(props: LogsTabProps): JSX.Element {
  const { datasetId } = props
  const { t } = useTranslation()
  const localeText = useDataGridLocaleText()

  const [status, setStatus] = useState<number>()
  const [pagination, setPagination] = useState<GridPaginationModel>({ page: 0, pageSize: 10 })
  const [openLogId, setOpenLogId] = useState<string>()

  const summary = useQuery(ingestionSummaryQueryOptions(datasetId))
  const logs = useQuery(
    ingestionLogsQueryOptions(datasetId, {
      status,
      page: pagination.page + 1,
      pageSize: pagination.pageSize,
    }),
  )

  const stats = [
    { id: 'all', label: t('datasets.logs.stats.all'), value: summary.data?.doc_num },
    {
      id: 'queued',
      label: t('datasets.logs.stats.queued'),
      value: summary.data?.status.unstart_count,
    },
    {
      id: 'running',
      label: t('datasets.logs.stats.running'),
      value: summary.data?.status.running_count,
    },
    {
      id: 'failed',
      label: t('datasets.logs.stats.failed'),
      value: summary.data?.status.fail_count,
    },
  ]

  const columns: GridColDef<IngestionLog>[] = [
    { field: 'id', headerName: t('datasets.logs.col.id'), width: 150 },
    { field: 'document_name', headerName: t('datasets.logs.col.file'), flex: 1, minWidth: 160 },
    { field: 'task_type', headerName: t('datasets.logs.col.type'), width: 100 },
    { field: 'process_begin_at', headerName: t('datasets.logs.col.start'), width: 170 },
    {
      field: 'process_duration',
      headerName: t('datasets.logs.col.duration'),
      width: 100,
      renderCell: (params) => `${params.row.process_duration.toFixed(1)} s`,
    },
    {
      field: 'operation_status',
      headerName: t('datasets.logs.col.status'),
      width: 130,
      renderCell: (params) => <IngestionStatusChip status={params.row.operation_status} />,
    },
    {
      field: 'actions',
      headerName: t('datasets.logs.col.log'),
      width: 90,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) => (
        <IconButton
          size="small"
          aria-label={t('datasets.logs.showLog', { name: params.row.document_name })}
          onClick={() => setOpenLogId(params.row.id)}
        >
          <ArticleOutlinedIcon fontSize="small" />
        </IconButton>
      ),
    },
  ]

  function retry(): void {
    void summary.refetch()
    void logs.refetch()
  }

  if (summary.isError || logs.isError) {
    return <QueryError message={t('datasets.logs.error')} onRetry={retry} />
  }

  return (
    <Stack spacing={2}>
      <Grid container spacing={2}>
        {stats.map((stat) => (
          <Grid key={stat.id} size={{ xs: 12, sm: 6, md: 3 }}>
            <StatCard id={stat.id} label={stat.label} value={stat.value} />
          </Grid>
        ))}
      </Grid>

      <TextField
        select
        size="small"
        label={t('datasets.logs.filter.label')}
        value={status === undefined ? 'all' : String(status)}
        onChange={(event) => {
          setStatus(event.target.value === 'all' ? undefined : Number(event.target.value))
          setPagination((current) => ({ ...current, page: 0 }))
        }}
        sx={{ maxWidth: 240 }}
      >
        <MenuItem value="all">{t('datasets.logs.filter.all')}</MenuItem>
        {STATUS_CODES.map((code) => (
          <MenuItem key={code} value={String(code)}>
            {t(`datasets.logs.status.${code}`)}
          </MenuItem>
        ))}
      </TextField>

      <DataGrid<IngestionLog>
        rows={logs.data?.logs ?? []}
        columns={columns}
        loading={logs.isPending || logs.isFetching}
        rowCount={logs.data?.total ?? 0}
        paginationMode="server"
        pagination
        paginationModel={pagination}
        onPaginationModelChange={setPagination}
        pageSizeOptions={PAGE_SIZE_OPTIONS}
        disableVirtualization
        disableRowSelectionOnClick
        localeText={localeText}
        slots={{ noRowsOverlay: NoRowsOverlay }}
        sx={{ height: GRID_HEIGHT }}
      />

      {openLogId !== undefined ? (
        <IngestionLogDialog
          datasetId={datasetId}
          logId={openLogId}
          onClose={() => setOpenLogId(undefined)}
        />
      ) : null}
    </Stack>
  )
}
