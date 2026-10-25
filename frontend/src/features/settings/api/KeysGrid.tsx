/**
 * Siatka kluczy API (brief E3-6c1 T4 pkt 2; V12-3 T2): kolumny Nazwa (z „—” gdy brak; pełna
 * nazwa w `title`, wielokropek domyślny `DataGrid`), Token (maska), Utworzono i Akcje
 * (kopiowanie pełnego tokenu oraz usuwanie z potwierdzeniem). Plik ładuje `ApiKeysPage`
 * przez `lazy`, dzięki czemu `@mui/x-data-grid` nie trafia do chunku strony.
 * Schemat `ApiToken` od v1.2 ma pole `name` (kontrakt V12-3); daty wygaśnięcia nadal brak,
 * więc kolumny „Wygasa” nie ma.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import IconButton from '@mui/material/IconButton'
import Snackbar from '@mui/material/Snackbar'
import Stack from '@mui/material/Stack'
import { DataGrid } from '@mui/x-data-grid'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import { ConfirmDialog } from '../../../components/ConfirmDialog'
import { EmptyState } from '../../../components/EmptyState'
import { RowActionsMenu } from '../../../components/RowActionsMenu'
import { actionsFirst, useCompactGrid } from '../../../components/gridCompact'
import { useDataGridLocaleText } from '../../../hooks/useDataGridLocaleText'
import { resolveLanguage } from '../../../i18n'
import { formatDateTime } from '../../../lib/format'
import { maskToken, useDeleteToken } from '../queries'
import type { ApiToken } from '../queries'
import { copyToClipboard } from './copyToClipboard'

/** Wysokość siatki — jsdom nie mierzy kontenera, a `disableVirtualization` renderuje wiersze. */
const GRID_HEIGHT = 420

/** Tekst błędu: nagłówek z i18n plus komunikat z API (kontrakt §0). */
function errorText(error: unknown, title: string, fallback: string): string {
  const message = error instanceof ApiError && error.message !== '' ? error.message : fallback
  return `${title}: ${message}`
}

export type KeysGridProps = {
  rows: ApiToken[]
  loading: boolean
}

function NoRowsOverlay(): JSX.Element {
  const { t } = useTranslation()

  return <EmptyState title={t('settings.keys.empty')} />
}

export function KeysGrid(props: KeysGridProps): JSX.Element {
  const { rows, loading } = props
  const { t, i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  const localeText = useDataGridLocaleText()
  const deleteToken = useDeleteToken()
  // Wzorzec < md (kontrakt WP E3-7 §C2): kolumna akcji pierwsza, jej treścią menu ⋮.
  const compact = useCompactGrid()
  // Token czekający na potwierdzenie usunięcia; `null` = okno zamknięte.
  const [pending, setPending] = useState<string | null>(null)
  // Odzew kopiowania z tabeli (MINOR z QA-UI E6-2-2): Snackbar — czytelny też w trybie
  // < md, gdzie klik w pozycji menu ⋮ zamyka menu i nie ma czego podświetlić w wierszu.
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)

  /** Kopiuje pełny token i pokazuje wynik; porażka dostaje czytelny komunikat. */
  async function copyToken(token: string): Promise<void> {
    const ok = await copyToClipboard(token)
    setCopied(ok)
    setCopyFailed(!ok)
  }

  function confirmDelete(): void {
    if (pending === null) return
    deleteToken.reset()
    deleteToken.mutate(pending)
    setPending(null)
  }

  const columns: GridColDef<ApiToken>[] = [
    {
      field: 'name',
      headerName: t('settings.keys.col.name'),
      flex: 1,
      // Compact (< md): nazwa zwęża się do minimum (min 90) — suma minimów Nazwa+Token+⋮
      // mieści się przy 390 px bez poziomego przewijania (SC-V12-01).
      minWidth: compact ? 90 : 160,
      sortable: false,
      // Bez `renderCell`: `DataGrid` sam pokazuje formattedValue z wielokropkiem i pełną nazwą
      // w atrybucie `title` komórki (SC-V12-01, wariant 390); brak nazwy to „—”, nie pusta.
      valueFormatter: (value) =>
        value === null || value === '' ? t('settings.keys.noName') : value,
    },
    {
      field: 'token',
      headerName: t('settings.keys.col.token'),
      flex: 1,
      // Compact (< md): token zachowuje minWidth — czytelna maska na wąskim ekranie.
      minWidth: compact ? 150 : 260,
      sortable: false,
      renderCell: (params) => (
        <Box component="span" sx={{ fontFamily: 'monospace' }}>
          {maskToken(params.row.token)}
        </Box>
      ),
    },
    // Compact (< md): kolumna „Utworzono” zwinięta — po dodaniu Nazwy (V12-3 T2) suma minimów
    // Nazwa+Token+Utworzono+⋮ (90+150+90+64) przekracza ~358 px dostępną przy 390 px i wykręca
    // poziomy przewijacz; na wąskim ekranie data utworzenia ustępuje nazwie i masce tokenu.
    ...(compact
      ? []
      : [
          {
            field: 'create_date',
            headerName: t('settings.keys.col.created'),
            width: 200,
            sortable: false,
            renderCell: (params) =>
              params.row.create_date === null || params.row.create_date === undefined
                ? ''
                : formatDateTime(params.row.create_date, language),
          } satisfies GridColDef<ApiToken>,
        ]),
    {
      field: 'actions',
      headerName: t('settings.keys.col.actions'),
      width: compact ? 64 : 120,
      sortable: false,
      filterable: false,
      disableColumnMenu: true,
      renderCell: (params) =>
        compact ? (
          <RowActionsMenu
            ariaLabel={t('common.rowActions')}
            items={[
              {
                key: 'copy',
                label: t('settings.keys.copyToken'),
                onClick: () => {
                  void copyToken(params.row.token)
                },
              },
              {
                key: 'delete',
                label: t('settings.keys.delete'),
                onClick: () => setPending(params.row.token),
              },
            ]}
          />
        ) : (
          <Stack direction="row">
            <IconButton
              size="small"
              aria-label={`${t('settings.keys.copyToken')} ${maskToken(params.row.token)}`}
              onClick={() => {
                void copyToken(params.row.token)
              }}
            >
              <ContentCopyRoundedIcon fontSize="small" />
            </IconButton>
            <IconButton
              size="small"
              aria-label={`${t('settings.keys.delete')} ${maskToken(params.row.token)}`}
              onClick={() => setPending(params.row.token)}
            >
              <DeleteOutlineRoundedIcon fontSize="small" />
            </IconButton>
          </Stack>
        ),
    },
  ]

  return (
    <Stack spacing={2}>
      {deleteToken.isError ? (
        <Alert severity="error">
          {errorText(deleteToken.error, t('settings.error.title'), t('settings.keys.error'))}
        </Alert>
      ) : null}
      <DataGrid<ApiToken>
        rows={rows}
        columns={actionsFirst(columns, compact)}
        loading={loading}
        // Identyfikator wiersza trafia do `data-id` w DOM — nie może nim być pełny token (DEC-126).
        // Maska (12+4 znaki) plus czas utworzenia wystarcza do rozróżnienia wierszy w liście.
        getRowId={(row) => `${row.create_time}:${maskToken(row.token)}`}
        aria-label={t('settings.keys.gridLabel')}
        localeText={localeText}
        disableVirtualization
        // Compact: ikona menu ostatniego nagłówka wystaje poza siatkę i dokłada poziomy przewijacz
        // (nagłówek „Utworzono” ucięty) — bez niej siatka się mieści.
        disableColumnMenu={compact}
        disableRowSelectionOnClick
        slots={{ noRowsOverlay: NoRowsOverlay }}
        sx={{
          height: GRID_HEIGHT,
          // Separator ostatniego nagłówka wystaje o ~5 px poza siatkę (poziomy przewijacz).
          '& .MuiDataGrid-columnSeparator': { display: compact ? 'none' : undefined },
        }}
      />
      <ConfirmDialog
        open={pending !== null}
        title={t('settings.keys.deleteTitle')}
        message={t('settings.keys.deleteMessage', {
          token: pending === null ? '' : maskToken(pending),
        })}
        confirmLabel={t('settings.common.delete')}
        cancelLabel={t('settings.common.cancel')}
        onConfirm={confirmDelete}
        onCancel={() => setPending(null)}
      />
      <Snackbar
        open={copied || copyFailed}
        autoHideDuration={2000}
        message={copyFailed ? t('settings.common.copyFailed') : t('settings.common.copied')}
        onClose={() => {
          setCopied(false)
          setCopyFailed(false)
        }}
        data-testid="keys-copy-snackbar"
      />
    </Stack>
  )
}
