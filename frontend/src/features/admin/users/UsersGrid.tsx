/**
 * Siatka użytkowników (kontrakt WP E3-6c2 §4 i §T3 pkt 1): `DataGrid` w trybie serwerowym —
 * wiersze i `total` dostaje od `UsersPage`, a `rowCount` bierze z `total`, więc paginacja
 * i szukanie są po stronie backendu. Plik ładuje `UsersPage` przez `lazy`, dzięki czemu
 * `@mui/x-data-grid` nie trafia do chunku strony.
 */

import type { JSX } from 'react'
import { DataGrid } from '@mui/x-data-grid'
import type { GridPaginationModel } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../../../components/EmptyState'
import {
  actionsFirst,
  useCompactGrid,
  useNarrowGrid,
  useStickyColumns,
} from '../../../components/gridCompact'
import { ScrollShadowBox, withEllipsisHeaders } from '../../../components/ScrollShadowBox'
import { useDataGridLocaleText } from '../../../hooks/useDataGridLocaleText'
import { resolveLanguage } from '../../../i18n'
import { USERS_PAGE_SIZE_OPTIONS } from '../constants'
import type { WdUser } from '../queries'

import { buildUserColumns } from './userColumns'
import type { UserActionKind } from './UserActionsMenu'

/** Wysokość siatki — jsdom nie mierzy kontenera, a `disableVirtualization` renderuje wiersze. */
const GRID_HEIGHT = 420

export type UsersGridProps = {
  rows: WdUser[]
  total: number
  loading: boolean
  pagination: GridPaginationModel
  onPaginationModelChange: (model: GridPaginationModel) => void
  selfId: string | null
  onToggleActive: (user: WdUser, active: boolean) => void
  onAction: (user: WdUser, kind: UserActionKind) => void
}

function NoRowsOverlay(): JSX.Element {
  const { t } = useTranslation()

  return <EmptyState title={t('admin.users.empty')} />
}

export function UsersGrid(props: UsersGridProps): JSX.Element {
  const { rows, total, loading, pagination, onPaginationModelChange, selfId } = props
  const { i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  const localeText = useDataGridLocaleText()

  // Wzorzec < md (kontrakt WP E3-7 §C2): kolumna akcji pierwsza, jej treścią menu ⋮.
  const compact = useCompactGrid()
  // T12 (QA końcowy A): na wąskim ekranie E-mail 170 px zamiast 200 px — przy 390 px
  // przyklejona kolumna zostawia pas przewijanej treści >= 150 px (scroller ~340 px).
  const emailMinWidth = useNarrowGrid() ? 170 : 200
  const columns = withEllipsisHeaders(
    actionsFirst(
      buildUserColumns({
        language,
        compact,
        emailMinWidth,
        selfId,
        onToggleActive: props.onToggleActive,
        onAction: props.onAction,
      }),
      compact,
    ),
  )

  return (
    <ScrollShadowBox
      scrollTargetSelector=".MuiDataGrid-virtualScroller"
      // Tabele wąskie (K5 + D3 z QA E5-H9-2): <= 600 px przyklejony tylko e-mail, 600–900 px
      // także ⋮, desktop tylko pierwsza kolumna — bez checkboxa, siatka nie zaznacza wierszy.
      stickyFields={useStickyColumns('email', emailMinWidth, { actions: 'actions' })}
    >
      <DataGrid<WdUser>
        rows={rows}
        columns={columns}
        loading={loading}
        rowCount={total}
        paginationMode="server"
        pagination
        paginationModel={pagination}
        onPaginationModelChange={onPaginationModelChange}
        pageSizeOptions={USERS_PAGE_SIZE_OPTIONS}
        localeText={localeText}
        disableVirtualization
        disableRowSelectionOnClick
        slots={{ noRowsOverlay: NoRowsOverlay }}
        sx={{ height: GRID_HEIGHT }}
      />
    </ScrollShadowBox>
  )
}
