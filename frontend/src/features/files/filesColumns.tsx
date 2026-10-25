/**
 * Kolumny siatki plików (kontrakt WP E4-5c §4, spec 08 §7.10): Nazwa, Data, Rozmiar, Datasety,
 * Akcje. `buildColumns` dostaje zależności strony (język, callbacki) i zwraca definicje kolumn,
 * dzięki czemu plik nie zna `FilesPage` i da się testować osobno. Etykiety bierzemy z instancji
 * `i18n` — siatka odświeża się przy zmianie języka razem z rodzicem. Sortowanie pomijamy
 * (`sortable: false`) — serwerowy domyślny porządek to `create_time` malejąco.
 */

import FolderIcon from '@mui/icons-material/Folder'
import InsertDriveFileOutlinedIcon from '@mui/icons-material/InsertDriveFileOutlined'
import Chip from '@mui/material/Chip'
import Link from '@mui/material/Link'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { Link as RouterLink } from '@tanstack/react-router'
import type { GridColDef } from '@mui/x-data-grid'

import { RowActionsMenu } from '../../components/RowActionsMenu'
import { i18n } from '../../i18n'
import type { Language } from '../../i18n'
import { formatBytes, formatDateTime } from '../../lib/format'

import { FileRowActions, buildFileRowActionItems } from './FileRowActions'
import type { FileAction } from './FileRowActions'
import type { FileItem } from './queries'

export type FilesColumnsContext = {
  language: Language
  /** Wzorzec < md (kontrakt WP E3-7 §C2): kolumna akcji na początku, treścią menu ⋮. */
  compact: boolean
  /** Klik nazwy folderu — wchodzi do środka (kontrakt §7). */
  onOpenFolder: (id: string) => void
  /** Klik przycisku akcji wiersza — `FilesPage` (T4) otwiera właściwy dialog. */
  onAction: (action: FileAction, file: FileItem) => void
}

export function buildColumns(ctx: FilesColumnsContext): GridColDef<FileItem>[] {
  const { language } = ctx

  return [
    {
      field: 'name',
      headerName: i18n.t('files.col.name'),
      flex: 1,
      // minWidth dobrane tak, by suma kolumn mieściła się w kontenerze przy 1280 px bez
      // przewijania poziomego (T7, R-UI-04: kosz przycięty prawą krawędzią na bazie).
      minWidth: 190,
      sortable: false,
      renderCell: (params) => (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', minWidth: 0 }}>
          {params.row.type === 'folder' ? (
            <FolderIcon fontSize="small" color="action" />
          ) : (
            <InsertDriveFileOutlinedIcon fontSize="small" color="action" />
          )}
          {params.row.type === 'folder' ? (
            <Link
              component="button"
              type="button"
              underline="hover"
              onClick={() => ctx.onOpenFolder(params.row.id)}
            >
              {params.row.name}
            </Link>
          ) : (
            <Typography variant="body2" noWrap>
              {params.row.name}
            </Typography>
          )}
        </Stack>
      ),
    },
    {
      field: 'update_time',
      headerName: i18n.t('files.col.date'),
      // M2 (QA E5-H9-2): data EN „Oct 12, 2026, 4:47 AM” ma ~177 px treści — 160 ucinało ją
      // bez wielokropka; 200 mieści format EN i zwalnia miejsce kolumnie akcji (R-UI-04).
      width: 200,
      sortable: false,
      renderCell: (params) => formatDateTime(params.row.update_time, language),
    },
    {
      field: 'size',
      headerName: i18n.t('files.col.size'),
      width: 110,
      sortable: false,
      // Folder nie ma rozmiaru na liście (kontrakt §4) — pokazujemy myślnik.
      renderCell: (params) =>
        params.row.type === 'folder' ? '—' : formatBytes(params.row.size, language),
    },
    {
      field: 'kbs_info',
      headerName: i18n.t('files.col.datasets'),
      flex: 1,
      minWidth: 150,
      sortable: false,
      renderCell: (params) => (
        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
          {params.row.kbs_info.map((info) => (
            <RouterLink
              key={info.kb_id}
              to="/dataset/files/$id"
              params={{ id: info.kb_id }}
              data-testid="files-kb-chip"
              style={{ textDecoration: 'none' }}
            >
              <Chip size="small" label={info.kb_name} />
            </RouterLink>
          ))}
        </Stack>
      ),
    },
    {
      field: 'actions',
      headerName: i18n.t('files.col.actions'),
      // 6 przycisków po 40 px + 5 odstępów po 2 px + padding komórki = 270 (T7, R-UI-04).
      width: ctx.compact ? 64 : 270,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) =>
        ctx.compact ? (
          <RowActionsMenu
            items={buildFileRowActionItems(params.row, ctx.onAction)}
            ariaLabel={i18n.t('common.rowActions')}
          />
        ) : (
          <FileRowActions file={params.row} onAction={ctx.onAction} />
        ),
    },
  ]
}
