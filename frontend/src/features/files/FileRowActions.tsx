/**
 * Akcje pojedynczego wiersza listy plików (kontrakt WP E4-5c §4, §7): Połącz, Przenieś,
 * Zmień nazwę, Pobierz, Podgląd, Usuń. Komponent jest czysto prezentacyjny — decyzje i mutacje
 * należą do wołającego (`FilesPage`, T4). Foldery nie mają Połącz/Pobierz/Podgląd; Podgląd pliku
 * bez `kbs_info` jest zablokowany i objęty podpowiedzią (MUI nie pokazuje `Tooltip`a na
 * nieaktywnym przycisku, dlatego przycisk wraca do drzewa opakowany w `span`).
 */

import type { JSX } from 'react'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined'
import DriveFileMoveOutlinedIcon from '@mui/icons-material/DriveFileMoveOutlined'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import LinkRoundedIcon from '@mui/icons-material/LinkRounded'
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import { useTranslation } from 'react-i18next'

import type { RowActionItem } from '../../components/RowActionsMenu'
import { i18n } from '../../i18n'

import type { FileItem } from './queries'

/** Akcje wiersza przekazywane do `onAction` (kontrakt §7). */
export type FileAction = 'link' | 'move' | 'rename' | 'download' | 'preview' | 'delete'

export type FileRowActionsProps = {
  file: FileItem
  onAction: (action: FileAction, file: FileItem) => void
}

/**
 * Te same akcje co przyciski wiersza, jako dane menu ⋮ dla trybu compact (kontrakt WP E3-7 §C2).
 * Foldery nie mają link/download/preview; Podgląd bez `kbs_info` jest zablokowany. Etykiety
 * pochodzą z tych samych kluczy `files.action.*` co wersja desktop.
 */
export function buildFileRowActionItems(
  file: FileItem,
  onAction: (action: FileAction, file: FileItem) => void,
): RowActionItem[] {
  const isFolder = file.type === 'folder'
  const previewable = file.kbs_info.length > 0
  const items: RowActionItem[] = []

  if (!isFolder) {
    items.push({
      key: 'link',
      label: i18n.t('files.action.link'),
      icon: <LinkRoundedIcon />,
      onClick: () => onAction('link', file),
    })
  }
  items.push({
    key: 'move',
    label: i18n.t('files.action.move'),
    icon: <DriveFileMoveOutlinedIcon />,
    onClick: () => onAction('move', file),
  })
  items.push({
    key: 'rename',
    label: i18n.t('files.action.rename'),
    icon: <EditOutlinedIcon />,
    onClick: () => onAction('rename', file),
  })
  if (!isFolder) {
    items.push({
      key: 'download',
      label: i18n.t('files.action.download'),
      icon: <DownloadOutlinedIcon />,
      onClick: () => onAction('download', file),
    })
    items.push({
      key: 'preview',
      label: i18n.t('files.action.preview'),
      icon: <VisibilityOutlinedIcon />,
      onClick: () => onAction('preview', file),
      disabled: !previewable,
    })
  }
  items.push({
    key: 'delete',
    label: i18n.t('files.action.delete'),
    icon: <DeleteOutlineRoundedIcon />,
    onClick: () => onAction('delete', file),
  })

  return items
}

export function FileRowActions(props: FileRowActionsProps): JSX.Element {
  const { file, onAction } = props
  const { t } = useTranslation()
  const isFolder = file.type === 'folder'
  const previewable = file.kbs_info.length > 0

  function act(action: FileAction): void {
    onAction(action, file)
  }

  const previewButton = (
    <IconButton
      aria-label={t('files.action.preview')}
      disabled={!previewable}
      onClick={() => act('preview')}
    >
      <VisibilityOutlinedIcon />
    </IconButton>
  )

  return (
    // Odstęp 2 px (nie 4) — 6 przycisków mieści się w kolumnie 270 px przy 1280 px (T7, R-UI-04).
    <Stack direction="row" spacing={0.25} sx={{ alignItems: 'center' }}>
      {isFolder ? null : (
        <IconButton aria-label={t('files.action.link')} onClick={() => act('link')}>
          <LinkRoundedIcon />
        </IconButton>
      )}
      <IconButton aria-label={t('files.action.move')} onClick={() => act('move')}>
        <DriveFileMoveOutlinedIcon />
      </IconButton>
      <IconButton aria-label={t('files.action.rename')} onClick={() => act('rename')}>
        <EditOutlinedIcon />
      </IconButton>
      {isFolder ? null : (
        <IconButton aria-label={t('files.action.download')} onClick={() => act('download')}>
          <DownloadOutlinedIcon />
        </IconButton>
      )}
      {isFolder ? null : previewable ? (
        previewButton
      ) : (
        <Tooltip title={t('files.action.previewDisabled')}>
          <span>{previewButton}</span>
        </Tooltip>
      )}
      <IconButton aria-label={t('files.action.delete')} onClick={() => act('delete')}>
        <DeleteOutlineRoundedIcon />
      </IconButton>
    </Stack>
  )
}
