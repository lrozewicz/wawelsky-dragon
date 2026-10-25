/**
 * Nagłówek szczegółów datasetu (08 §7.4, kontrakt WP E3-3a §T3): awatar 64 px z inicjałami nazwy,
 * nazwa jako `h1`, liczba plików z rozmiarem oraz data utworzenia.
 */

import type { JSX } from 'react'
import Avatar from '@mui/material/Avatar'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { resolveLanguage } from '../../../i18n'
import { formatBytes, formatDate } from '../../../lib/format'
import type { Dataset } from '../queries'

/** Inicjał nazwy: pierwsza litera lub cyfra (pomija nawiasy i znaki specjalne), jedna litera. */
export function datasetInitials(name: string): string {
  const first = /[\p{L}\p{N}]/u.exec(name)
  return first === null ? '?' : first[0].toUpperCase()
}

export type DatasetHeaderProps = {
  dataset: Dataset
}

export function DatasetHeader(props: DatasetHeaderProps): JSX.Element {
  const { dataset } = props
  const { t, i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  // Liczba plików przez plural i18next (`count_one/_few/_many/_other`); rozmiar formatem jak dotąd.
  const meta = `${t('datasets.detail.count', { count: dataset.document_count })} · ${formatBytes(
    dataset.size ?? 0,
    language,
  )}`

  return (
    <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
      {/* Kolory marki: domyślne tło awatara MUI (grey.400) nie osiąga kontrastu WCAG AA
          z jasnym tekstem — para primary.main/primary.contrastText przechodzi próg 4.5:1. */}
      <Avatar
        sx={{
          width: 64,
          height: 64,
          fontSize: 24,
          bgcolor: 'primary.main',
          color: 'primary.contrastText',
        }}
      >
        {datasetInitials(dataset.name)}
      </Avatar>
      <Stack spacing={0.5} sx={{ minWidth: 0 }}>
        <Typography component="h1" variant="h5" noWrap>
          {dataset.name}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {meta}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t('datasets.detail.createdAt', { date: formatDate(dataset.create_time, language) })}
        </Typography>
      </Stack>
    </Stack>
  )
}
