/**
 * Chipy „Pytania pokrewne” (kontrakt WP E4-4b §4): tytuł i jeden klikalny `Chip` na pozycję.
 * Pusta lista nie renderuje nic — sekcja znika, gdy nie ma pytań (albo wyszukiwanie ich nie zwraca).
 */

import type { JSX } from 'react'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

export type RelatedChipsProps = {
  items: string[]
  onPick: (q: string) => void
}

export function RelatedChips(props: RelatedChipsProps): JSX.Element | null {
  const { items, onPick } = props
  const { t } = useTranslation()

  if (items.length === 0) return null

  return (
    <Stack spacing={1} data-testid="related-chips">
      <Typography variant="subtitle2">{t('searches.related.title')}</Typography>
      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
        {items.map((item) => (
          <Chip key={item} clickable label={item} onClick={() => onPick(item)} />
        ))}
      </Stack>
    </Stack>
  )
}
