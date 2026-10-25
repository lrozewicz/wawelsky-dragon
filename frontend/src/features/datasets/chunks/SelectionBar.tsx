/**
 * Pasek akcji zbiorczych listy chunków (kontrakt WP E3-4a §SelectionBar). Widoczny tylko przy
 * niepustym zaznaczeniu i czysto prezentacyjny — mutacje oraz czyszczenie zaznaczenia należą do
 * panelu (T4). „Zaznacz stronę” jest nieaktywne, gdy bieżąca strona nie ma czego zaznaczać.
 */

import type { JSX } from 'react'
import Button from '@mui/material/Button'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

export type SelectionBarProps = {
  selectedCount: number
  /** Liczba chunków na bieżącej stronie. */
  pageSize: number
  allOnPageSelected: boolean
  /** „Zaznacz stronę” / odznacz — zależnie od `allOnPageSelected`. */
  onTogglePage: () => void
  onEnable: () => void
  onDisable: () => void
  onDelete: () => void
}

export function SelectionBar(props: SelectionBarProps): JSX.Element | null {
  const { selectedCount, pageSize, allOnPageSelected } = props
  const { onTogglePage, onEnable, onDisable, onDelete } = props
  const { t } = useTranslation()

  if (selectedCount === 0) return null

  return (
    <Paper data-testid="chunks-selection-bar" variant="outlined" sx={{ px: 2, py: 1 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
        <Typography variant="body2" sx={{ mr: 1 }}>
          {t('chunks.selection.count', { count: selectedCount })}
        </Typography>
        <Button
          size="small"
          data-testid="chunks-select-page"
          disabled={pageSize === 0}
          onClick={onTogglePage}
        >
          {allOnPageSelected ? t('chunks.selection.unpage') : t('chunks.selection.page')}
        </Button>
        <Button size="small" data-testid="chunks-bulk-enable" onClick={onEnable}>
          {t('chunks.selection.enable')}
        </Button>
        <Button size="small" data-testid="chunks-bulk-disable" onClick={onDisable}>
          {t('chunks.selection.disable')}
        </Button>
        <Button size="small" color="error" data-testid="chunks-bulk-delete" onClick={onDelete}>
          {t('chunks.selection.delete')}
        </Button>
      </Stack>
    </Paper>
  )
}
