/**
 * Kolumny siatki użytkowników (kontrakt WP E3-6c2 §4 i §T3 pkt 2). `buildUserColumns` dostaje
 * zależności siatki (identyfikator zalogowanego konta, język, callbacki akcji) i zwraca definicje
 * kolumn, dzięki czemu plik nie zna `UsersGrid`. Etykiety bierzemy z instancji `i18n` — siatka
 * odświeża się przy zmianie języka razem z rodzicem (wzór: `filesColumns.tsx`).
 */

import Chip from '@mui/material/Chip'
import Switch from '@mui/material/Switch'
import type { GridColDef } from '@mui/x-data-grid'

import { RowActionsMenu } from '../../../components/RowActionsMenu'
import type { RowActionItem } from '../../../components/RowActionsMenu'
import { i18n } from '../../../i18n'
import type { Language } from '../../../i18n'
import type { WdUser } from '../queries'

import { UserActionsMenu } from './UserActionsMenu'
import type { UserActionKind } from './UserActionsMenu'

export type UserColumnsContext = {
  language: Language
  /** Wzorzec < md (kontrakt WP E3-7 §C2): kolumna akcji na początku, treścią menu ⋮. */
  compact: boolean
  /**
   * Szerokość minimalna kolumny E-mail (T12, QA końcowy A): na wąskim ekranie (<= 600 px)
   * 170 px zamiast 200 px — przyklejony E-mail zostawia pas przewijanej treści >= 150 px
   * przy 390 px; poza nim 200 px (desktop bez zmian, kolumna i tak rozciąga się przez `flex`).
   */
  emailMinWidth: number
  /** Identyfikator zalogowanego konta — jego wiersz blokuje przełącznik „Aktywny”. */
  selfId: string | null
  /** Przełączenie aktywności — nowy stan przełącznika. */
  onToggleActive: (user: WdUser, active: boolean) => void
  /** Wybór pozycji menu akcji wiersza. */
  onAction: (user: WdUser, kind: UserActionKind) => void
}

/** Pozycje menu ⋮ (kontrakt §C2) — ten sam zestaw co desktopowe `UserActionsMenu`. */
function buildActionItems(row: WdUser, ctx: UserColumnsContext): RowActionItem[] {
  const isSelf = ctx.selfId !== null && row.id === ctx.selfId
  const items: RowActionItem[] = [
    {
      key: 'details',
      label: i18n.t('admin.users.actions.details'),
      onClick: () => ctx.onAction(row, 'details'),
    },
  ]
  if (row.auth_source === 'local') {
    items.push({
      key: 'password',
      label: i18n.t('admin.users.actions.password'),
      onClick: () => ctx.onAction(row, 'password'),
    })
  }
  items.push(
    {
      key: 'role',
      label: i18n.t(
        row.is_superuser ? 'admin.users.actions.revokeAdmin' : 'admin.users.actions.makeAdmin',
      ),
      onClick: () => ctx.onAction(row, 'role'),
      disabled: isSelf,
    },
    {
      key: 'keys',
      label: i18n.t('admin.users.actions.keys'),
      onClick: () => ctx.onAction(row, 'keys'),
    },
    {
      key: 'delete',
      label: i18n.t('admin.users.actions.delete'),
      onClick: () => ctx.onAction(row, 'delete'),
      disabled: isSelf,
    },
  )
  return items
}

export function buildUserColumns(ctx: UserColumnsContext): GridColDef<WdUser>[] {
  const { language, selfId } = ctx

  return [
    {
      field: 'email',
      headerName: i18n.t('admin.users.col.email'),
      flex: 1,
      minWidth: ctx.emailMinWidth,
      sortable: false,
    },
    {
      field: 'nickname',
      headerName: i18n.t('admin.users.col.nickname'),
      flex: 1,
      minWidth: 130,
      sortable: false,
    },
    {
      field: 'is_superuser',
      headerName: i18n.t('admin.users.col.role'),
      width: 140,
      sortable: false,
      renderCell: (params) => (
        <Chip
          size="small"
          label={i18n.t(
            params.row.is_superuser ? 'admin.users.role.admin' : 'admin.users.role.user',
          )}
        />
      ),
    },
    {
      field: 'auth_source',
      headerName: i18n.t('admin.users.col.source'),
      width: 100,
      sortable: false,
      // Nieznane źródło uwierzytelnienia pokazujemy surowo (kontrakt §T3 pkt 2).
      renderCell: (params) =>
        i18n.t(`admin.users.source.${params.row.auth_source}`, {
          defaultValue: params.row.auth_source,
        }),
    },
    {
      field: 'is_active',
      headerName: i18n.t('admin.users.col.active'),
      width: 100,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) => (
        <Switch
          size="small"
          checked={params.row.is_active}
          disabled={selfId !== null && params.row.id === selfId}
          // Etykieta trafia na sam `input`; MUI 9 nie zna już `inputProps` (wzór: `filesColumns.tsx`).
          slotProps={{ input: { 'aria-label': params.row.email } }}
          onChange={(event) => ctx.onToggleActive(params.row, event.target.checked)}
        />
      ),
    },
    {
      field: 'created_at',
      headerName: i18n.t('admin.users.col.created'),
      // „10/14/2026, 6:40:25 PM” (EN) ma ~165 px treści + padding (E67-z2 T3: 180 ucinało datę).
      width: 200,
      sortable: false,
      renderCell: (params) =>
        params.row.created_at === null
          ? ''
          : new Date(params.row.created_at).toLocaleString(language),
    },
    {
      field: 'actions',
      headerName: i18n.t('admin.users.col.actions'),
      // Nagłówek „Actions” (EN) ma ~55 px treści + padding (E67-z2 T3: 90/64 ucinało go do „Acti…”).
      width: ctx.compact ? 84 : 100,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) =>
        ctx.compact ? (
          <RowActionsMenu
            items={buildActionItems(params.row, ctx)}
            ariaLabel={i18n.t('common.rowActions')}
          />
        ) : (
          <UserActionsMenu
            user={params.row}
            selfId={selfId}
            onAction={(kind) => ctx.onAction(params.row, kind)}
          />
        ),
    },
  ]
}
