/**
 * Pasek akcji zbiorczych listy Plików (kontrakt WP E4-5c §7): widoczny tylko przy niepustym
 * zaznaczeniu. Czysto prezentacyjny — mutacje, czyszczenie zaznaczenia i decyzję o dostępności
 * „Połącz” obsługuje `useFilesActions` (T4). Wzór: `features/datasets/files/BulkActionBar.tsx`.
 */

import type { JSX } from 'react'
import CloseIcon from '@mui/icons-material/Close'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import DriveFileMoveOutlinedIcon from '@mui/icons-material/DriveFileMoveOutlined'
import LinkRoundedIcon from '@mui/icons-material/LinkRounded'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

export type FilesBulkBarProps = {
  count: number
  /** Zaznaczone są same foldery — UI pokazuje „Połącz” tylko dla plików (kontrakt §7 p. 2). */
  linkDisabled: boolean
  onLink: () => void
  onMove: () => void
  onDelete: () => void
  onClear: () => void
}

export function FilesBulkBar(props: FilesBulkBarProps): JSX.Element | null {
  const { count, linkDisabled, onLink, onMove, onDelete, onClear } = props
  const { t } = useTranslation()

  if (count === 0) return null

  return (
    <Paper data-testid="files-bulk-bar" variant="outlined" sx={{ px: 2, py: 1 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Typography variant="body2" sx={{ mr: 1 }}>
          {t('files.bulk.selected', { count })}
        </Typography>
        <Button
          data-testid="files-bulk-link"
          startIcon={<LinkRoundedIcon />}
          disabled={linkDisabled}
          onClick={onLink}
        >
          {t('files.bulk.link')}
        </Button>
        <Button
          data-testid="files-bulk-move"
          startIcon={<DriveFileMoveOutlinedIcon />}
          onClick={onMove}
        >
          {t('files.bulk.move')}
        </Button>
        <Button
          data-testid="files-bulk-delete"
          color="error"
          startIcon={<DeleteOutlineRoundedIcon />}
          onClick={onDelete}
        >
          {t('files.bulk.delete')}
        </Button>
        <IconButton aria-label={t('common.cancel')} onClick={onClear}>
          <CloseIcon />
        </IconButton>
      </Stack>
    </Paper>
  )
}
