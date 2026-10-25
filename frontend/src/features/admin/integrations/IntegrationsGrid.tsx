/**
 * Siatka integracji (kontrakt WP E4-3c §1 i §T2 pkt 2–4): kolumny nazwy, datasetu, harmonogramu,
 * ostatniego przebiegu (chip + data), aktywności i akcji. Poniżej progu `md` chowamy kolumnę
 * datasetu (`columnVisibilityModel`), a kontener przewija się poziomo — mobile 390 px.
 * Siatka jest kliencka (`rows` z rodzica), bez paginacji serwerowej.
 */

import type { JSX } from 'react'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import Box from '@mui/material/Box'
import { DataGrid } from '@mui/x-data-grid'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'

import { RowActionsMenu } from '../../../components/RowActionsMenu'
import { actionsFirst, useCompactGrid, useStickyColumns } from '../../../components/gridCompact'
import { ScrollShadowBox } from '../../../components/ScrollShadowBox'
import { useDataGridLocaleText } from '../../../hooks/useDataGridLocaleText'
import { resolveLanguage } from '../../../i18n'

import type { Integration } from './queries'
import { StatusChip } from './StatusChip'

export type IntegrationsGridProps = {
  rows: Integration[]
  /** Otwarcie szczegółów integracji (klik nazwy albo przycisk „Szczegóły"). */
  onOpen: (id: number) => void
  /** Otwarcie formularza edycji wskazanej integracji. */
  onEdit: (integration: Integration) => void
}

export function IntegrationsGrid(props: IntegrationsGridProps): JSX.Element {
  const { rows, onOpen, onEdit } = props
  const { t, i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  const localeText = useDataGridLocaleText()
  // Wzorzec < md (kontrakt WP E3-7 §C2): akcje na początku jako menu ⋮, a kolumna datasetu znika.
  const compact = useCompactGrid()
  // U3 (K5 + D3): <= 600 px przyklejona sama nazwa (⋮ tylko, gdy mieści się z nią w ~45% okna),
  // 600–900 px także ⋮ — pierwszy wiersz wzorca jak w UsersGrid/FilesGrid.
  const stickyFields = useStickyColumns('name', 180, { actions: 'actions' })

  const columns: GridColDef<Integration>[] = [
    {
      field: 'name',
      headerName: t('integrations.list.col.name'),
      flex: 1,
      minWidth: 180,
      sortable: false,
      // Komórka nazwy jest przyciskiem otwierającym szczegóły (kontrakt §1). Długa nazwa:
      // wielokropek + pełna nazwa w podpowiedzi (U2) — przycisk wyrównany do komórki, bez
      // przycięcia prawą krawędzią (cut-off kompaktowej siatki na 390 px, SC-V13-12).
      renderCell: (params) => (
        <Button
          variant="text"
          data-testid={`integration-name-${params.row.id}`}
          title={params.row.name}
          onClick={() => onOpen(params.row.id)}
          sx={{ textTransform: 'none', justifyContent: 'flex-start', px: 0.5, minWidth: 0 }}
        >
          <Box
            component="span"
            sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          >
            {params.row.name}
          </Box>
        </Button>
      ),
    },
    {
      field: 'dataset_id',
      headerName: t('integrations.list.col.dataset'),
      width: 160,
      sortable: false,
    },
    {
      field: 'scan_interval_seconds',
      headerName: t('integrations.list.col.schedule'),
      width: 150,
      sortable: false,
      // Harmonogram: krótszy niż minuta w sekundach, dalej w minutach (§T2 pkt 2).
      renderCell: (params) =>
        params.row.scan_interval_seconds < 60
          ? t('integrations.list.every.seconds', { n: params.row.scan_interval_seconds })
          : t('integrations.list.every.minutes', {
              n: Math.round(params.row.scan_interval_seconds / 60),
            }),
    },
    {
      field: 'last_sync_status',
      headerName: t('integrations.list.col.lastRun'),
      width: 220,
      sortable: false,
      renderCell: (params) => (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <StatusChip status={params.row.last_sync_status} />
          <Typography variant="body2" color="text.secondary">
            {params.row.last_sync_at === null
              ? '—'
              : new Date(params.row.last_sync_at).toLocaleString(language)}
          </Typography>
        </Stack>
      ),
    },
    {
      field: 'is_active',
      headerName: t('integrations.list.col.active'),
      width: 110,
      sortable: false,
      renderCell: (params) =>
        t(params.row.is_active ? 'integrations.list.active.yes' : 'integrations.list.active.no'),
    },
    {
      field: 'actions',
      headerName: t('integrations.list.col.actions'),
      width: compact ? 64 : 190,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) =>
        compact ? (
          <RowActionsMenu
            ariaLabel={t('common.rowActions')}
            items={[
              {
                key: 'open',
                label: t('integrations.list.action.open'),
                onClick: () => onOpen(params.row.id),
              },
              {
                key: 'edit',
                label: t('integrations.list.action.edit'),
                onClick: () => onEdit(params.row),
              },
            ]}
          />
        ) : (
          <Stack direction="row" spacing={1}>
            <Button
              size="small"
              data-testid={`integration-open-${params.row.id}`}
              onClick={() => onOpen(params.row.id)}
            >
              {t('integrations.list.action.open')}
            </Button>
            <Button
              size="small"
              data-testid={`integration-edit-${params.row.id}`}
              onClick={() => onEdit(params.row)}
            >
              {t('integrations.list.action.edit')}
            </Button>
          </Stack>
        ),
    },
  ]

  return (
    // U3 (SC-V13-12): szeroka tabela przewija się wewnątrz własnego kontenera z cieniem,
    // pierwsza kolumna (nazwa) przyklejona — jak w UsersGrid/FilesGrid.
    <Box data-testid="integrations-grid">
      <ScrollShadowBox
        scrollTargetSelector=".MuiDataGrid-virtualScroller"
        stickyFields={stickyFields}
      >
        <DataGrid<Integration>
          rows={rows}
          columns={actionsFirst(columns, compact)}
          autoHeight
          localeText={localeText}
          // jsdom nie mierzy kontenera — wirtualizacja wyłączona renderuje wszystkie wiersze.
          disableVirtualization
          disableRowSelectionOnClick
          // Klucz modelu widoczności to `field` kolumny (`dataset_id`), nie sama nazwa danych.
          columnVisibilityModel={{ dataset_id: !compact }}
        />
      </ScrollShadowBox>
    </Box>
  )
}
