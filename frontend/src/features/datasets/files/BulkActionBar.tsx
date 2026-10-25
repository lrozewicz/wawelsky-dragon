/**
 * Pasek akcji zbiorczych listy plików (kontrakt WP E3-3b §T6). Widoczny tylko przy niepustym
 * zaznaczeniu (`count === 0` → `null`). Czysto prezentacyjny — mutacje i czyszczenie zaznaczenia
 * obsługuje wołający (T7).
 */

import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded'
import StopRoundedIcon from '@mui/icons-material/StopRounded'
import ToggleOffOutlinedIcon from '@mui/icons-material/ToggleOffOutlined'
import ToggleOnOutlinedIcon from '@mui/icons-material/ToggleOnOutlined'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

export type BulkActionBarProps = {
  count: number
  onParse: () => void
  onCancel: () => void
  onEnable: () => void
  onDisable: () => void
  onDelete: () => void
  onClear: () => void
}

export function BulkActionBar(props: BulkActionBarProps) {
  const { count, onParse, onCancel, onEnable, onDisable, onDelete, onClear } = props
  const { t } = useTranslation()

  if (count === 0) return null

  return (
    <Paper data-testid="bulk-bar" variant="outlined" sx={{ px: 2, py: 1 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Typography variant="body2" sx={{ mr: 1 }}>
          {t('datasets.files.bulk.selected', { n: count })}
        </Typography>
        <IconButton
          data-testid="bulk-parse"
          aria-label={t('datasets.files.bulk.parse')}
          onClick={onParse}
        >
          <PlayArrowRoundedIcon />
        </IconButton>
        <IconButton
          data-testid="bulk-cancel"
          aria-label={t('datasets.files.bulk.cancel')}
          onClick={onCancel}
        >
          <StopRoundedIcon />
        </IconButton>
        <IconButton
          data-testid="bulk-enable"
          aria-label={t('datasets.files.bulk.enable')}
          onClick={onEnable}
        >
          <ToggleOnOutlinedIcon />
        </IconButton>
        <IconButton
          data-testid="bulk-disable"
          aria-label={t('datasets.files.bulk.disable')}
          onClick={onDisable}
        >
          <ToggleOffOutlinedIcon />
        </IconButton>
        <IconButton
          data-testid="bulk-delete"
          aria-label={t('datasets.files.bulk.delete')}
          onClick={onDelete}
        >
          <DeleteOutlineRoundedIcon />
        </IconButton>
        <Button onClick={onClear}>{t('datasets.files.bulk.clear')}</Button>
      </Stack>
    </Paper>
  )
}
