/**
 * Styl ramki wiersza paska zadań wg statusu (QA D4, SC-E67-01): `done` w kolorze sukcesu motywu,
 * `failed` w kolorze błędu (tło alpha 0.12 jasny / 0.35 ciemny, kolor ciemnego schematu + ramka), reszta bez zmian.
 * Wydzielone z `TaskRow.tsx` przez limit rozmiaru pliku.
 */
import { alpha } from '@mui/material/styles'
import type { Theme } from '@mui/material/styles'

import { green, red } from '../../theme/themePrimitives'

import type { WdTaskStatus } from './types'

/** `success.main` / `error.main` schematu ciemnego (themePrimitives) — `theme.palette` jest zawsze jasny. */
const DARK_MAIN = { success: green[500], error: red[200] } as const

export function taskRowSx(status: WdTaskStatus, highlighted: boolean) {
  return (theme: Theme) => {
    const base = {
      p: 1,
      border: 1,
      borderColor: 'divider',
      borderRadius: 1,
      bgcolor: highlighted ? 'action.selected' : 'transparent',
    }
    if (status !== 'done' && status !== 'failed') return base
    // Paleta motywu pełnego zmiennych CSS: `theme.palette` to zawsze jasny schemat, ciemny jest w `colorSchemes`.
    const key = status === 'done' ? 'success' : 'error'
    const light = theme.palette[key].main
    const dark = DARK_MAIN[key]
    return {
      ...base,
      borderColor: light,
      bgcolor: alpha(light, 0.12),
      ...theme.applyStyles('dark', {
        borderColor: dark,
        bgcolor: alpha(dark, 0.35),
      }),
    }
  }
}
