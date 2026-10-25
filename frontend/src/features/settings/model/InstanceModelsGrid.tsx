/**
 * Siatka modeli instancji (brief E3-6c1 T6 pkt 2): nazwa, typ (etykieta i18n), max tokens,
 * wymiar (tylko embedding), przełącznik włączenia i usuwanie. Plik ładuje `InstanceModelsPanel`
 * przez `lazy`, dzięki czemu `@mui/x-data-grid` nie trafia do chunku strony.
 */

import type { JSX } from 'react'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import IconButton from '@mui/material/IconButton'
import Switch from '@mui/material/Switch'
import { DataGrid } from '@mui/x-data-grid'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../../../components/EmptyState'
import { RowActionsMenu } from '../../../components/RowActionsMenu'
import { actionsFirst, useCompactGrid, useStickyColumns } from '../../../components/gridCompact'
import { ScrollShadowBox, withEllipsisHeaders } from '../../../components/ScrollShadowBox'
import { useDataGridLocaleText } from '../../../hooks/useDataGridLocaleText'
import type { InstanceModel } from '../providerQueries'

/** Wysokość siatki — jsdom nie mierzy kontenera, a `disableVirtualization` renderuje wiersze. */
const GRID_HEIGHT = 420

/** Etykiety typów: `image2text` to backendowe oznaczenie modelu wizji (brief T6, uwaga). */
const TYPE_LABEL_KEYS: Record<string, string> = {
  chat: 'settings.models.type.chat',
  embedding: 'settings.models.type.embedding',
  rerank: 'settings.models.type.rerank',
  vision: 'settings.models.type.vision',
  image2text: 'settings.models.type.vision',
}

export type InstanceModelsGridProps = {
  rows: InstanceModel[]
  loading: boolean
  isSuperuser: boolean
  onToggle: (row: InstanceModel, active: boolean) => void
  onEdit: (row: InstanceModel) => void
  onDelete: (name: string) => void
}

function NoRowsOverlay(): JSX.Element {
  const { t } = useTranslation()

  return <EmptyState title={t('settings.models.empty')} />
}

export function InstanceModelsGrid(props: InstanceModelsGridProps): JSX.Element {
  const { rows, loading, isSuperuser } = props
  const { t } = useTranslation()
  const localeText = useDataGridLocaleText()
  // Wzorzec < md (kontrakt WP E3-7 §C2): kolumna akcji pierwsza, jej treścią menu ⋮.
  const compact = useCompactGrid()

  const columns: GridColDef<InstanceModel>[] = [
    {
      field: 'name',
      headerName: t('settings.models.col.name'),
      flex: 1,
      // T8 (D6): minWidth 120 (nie 130) — 10 px dla kolumny akcji (dwa IconButton 72 px +
      // padding 20 px nie mieściły się w 90 px, kosz ucinany do „…”); suma kolumn bez zmian
      // (645 px jak w T7), długie nazwy i tak skraca wielokropek (kolumna flex).
      minWidth: 120,
      sortable: false,
    },
    {
      field: 'model_type',
      headerName: t('settings.models.col.type'),
      // 100: wartość „Embedding” mieści się w komórce bez wielokropka (90 ucina do „Embed…” —
      // kontrolny zrzut T8; ten defekt widać w ciemnym motywie na wierszu fake-embed-1024).
      width: 100,
      sortable: false,
      renderCell: (params) => {
        const key = TYPE_LABEL_KEYS[params.row.model_type]
        return key === undefined ? params.row.model_type : t(key)
      },
    },
    {
      field: 'max_tokens',
      headerName: t('settings.models.col.maxTokens'),
      // 135: pełny nagłówek PL „Okno kontekstu” i EN „Context window” bez wielokropka
      // (wymóg wizualny T7; przy 120 PL ucinał się do „Okno kontek…”).
      width: 135,
      sortable: false,
      renderCell: (params) => params.row.max_tokens ?? t('settings.models.none'),
    },
    {
      field: 'wd_dimension',
      headerName: t('settings.models.col.dimension'),
      // 100: nagłówek EN „Dimension” mieści się bez ucięcia (90 ucina do „Dimensi…” —
      // kontrolny zrzut T8 w EN; T7 znało ten próg: 85 ucinało do „Dimens…”).
      width: 100,
      sortable: false,
      renderCell: (params) =>
        params.row.model_type === 'embedding' && params.row.wd_dimension != null
          ? params.row.wd_dimension
          : t('settings.models.none'),
    },
    {
      field: 'status',
      headerName: t('settings.models.col.active'),
      width: 90,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) => (
        <Switch
          size="small"
          checked={params.row.status === 'active'}
          disabled={!isSuperuser}
          slotProps={{
            input: { 'aria-label': t('settings.models.toggleAria', { name: params.row.name }) },
          }}
          onChange={(event) => props.onToggle(params.row, event.target.checked)}
        />
      ),
    },
    {
      field: 'actions',
      headerName: t('settings.models.col.actions'),
      // 100 (T8, D6): dwa IconButton po 36 px = 72 px + padding komórki 20 px = 92 px — przy 90
      // komórka się przepełniała i DataGrid obcinał kosz do „…” (scrollWidth 92 > clientWidth 90).
      width: compact ? 64 : 100,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) =>
        !isSuperuser ? null : compact ? (
          <RowActionsMenu
            ariaLabel={t('common.rowActions')}
            items={[
              {
                key: 'edit',
                label: t('settings.models.edit'),
                onClick: () => props.onEdit(params.row),
              },
              {
                key: 'delete',
                label: t('settings.models.delete'),
                onClick: () => props.onDelete(params.row.name),
              },
            ]}
          />
        ) : (
          <>
            <IconButton
              size="small"
              aria-label={`${t('settings.models.edit')} ${params.row.name}`}
              onClick={() => props.onEdit(params.row)}
            >
              <EditOutlinedIcon fontSize="small" />
            </IconButton>
            <IconButton
              size="small"
              aria-label={`${t('settings.models.delete')} ${params.row.name}`}
              onClick={() => props.onDelete(params.row.name)}
            >
              <DeleteOutlineRoundedIcon fontSize="small" />
            </IconButton>
          </>
        ),
    },
  ]

  return (
    <ScrollShadowBox
      scrollTargetSelector=".MuiDataGrid-virtualScroller"
      // Tabele wąskie (K5 + D3 z QA E5-H9-2): <= 600 px przyklejona tylko nazwa, 600–900 px
      // także ⋮ (Nazwa+⋮ mieszczą się w ~45% szerokości), desktop sama nazwa.
      stickyFields={useStickyColumns('name', 120, { actions: 'actions' })}
    >
      <DataGrid<InstanceModel>
        rows={rows}
        columns={withEllipsisHeaders(actionsFirst(columns, compact))}
        loading={loading}
        getRowId={(row) => row.name}
        aria-label={t('settings.models.gridLabel')}
        localeText={localeText}
        disableVirtualization
        disableRowSelectionOnClick
        slots={{ noRowsOverlay: NoRowsOverlay }}
        sx={{ height: GRID_HEIGHT }}
      />
    </ScrollShadowBox>
  )
}
