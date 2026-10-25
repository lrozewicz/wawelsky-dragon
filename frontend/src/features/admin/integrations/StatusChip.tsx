/**
 * Chip statusu integracji i przebiegu (kontrakt WP E4-3c §1): `null` znaczy „nigdy",
 * kolory odwzorowują stany przebiegu, a nieznany status pokazujemy surowo.
 * Używają go i lista (T2), i szczegóły (T4).
 */

import type { JSX } from 'react'
import Chip from '@mui/material/Chip'
import type { ChipProps } from '@mui/material/Chip'
import { useTranslation } from 'react-i18next'

/** Kolory stanów przebiegu (§1); nieznany status dostaje `default`. */
const STATUS_COLORS: Record<string, ChipProps['color']> = {
  success: 'success',
  partial: 'warning',
  failed: 'error',
  cancelled: 'default',
  running: 'info',
  queued: 'info',
}

export function StatusChip(props: { status: string | null }): JSX.Element {
  const { t } = useTranslation()
  const { status } = props

  if (status === null) {
    return <Chip size="small" color="default" label={t('integrations.status.never')} />
  }

  return (
    <Chip
      size="small"
      color={STATUS_COLORS[status] ?? 'default'}
      label={t(`integrations.status.${status}`, { defaultValue: status })}
    />
  )
}
