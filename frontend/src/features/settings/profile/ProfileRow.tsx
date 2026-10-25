/**
 * Wiersz karty profilu (kontrakt WP E3-6c1 §T3 p. 1): etykieta, wartość i opcjonalny przycisk
 * „Edytuj” (`settings.common.edit`). Wiersze bez akcji (e-mail) pokazują sam odczyt.
 */

import type { JSX } from 'react'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

export type ProfileRowProps = {
  /** Nazwa wiersza — z niej powstają `data-testid` wiersza i przycisku edycji. */
  name: string
  label: string
  value: string
  /**
   * Łamanie także wewnątrz słowa (`overflow-wrap: anywhere`) — tylko dla wartości będących
   * jednym długim „słowem” (adres e-mail), które inaczej wychodziłyby poza kartę (SC-E5-H8z-03).
   */
  breakAnywhere?: boolean
  /** Brak akcji = wiersz tylko do odczytu (bez przycisku). */
  onEdit?: () => void
}

export function ProfileRow(props: ProfileRowProps): JSX.Element {
  const { name, label, value, breakAnywhere = false, onEdit } = props
  const { t } = useTranslation()

  return (
    <Stack
      // W wąskim oknie etykieta nad wartością — w wierszu wartość (np. „Nie ustawiono”)
      // nie mieści się obok etykiety i „Edytuj”, a `word-break` rozerwałby słowo (SC-E5-H8z-03).
      direction={{ xs: 'column', sm: 'row' }}
      spacing={2}
      sx={{ alignItems: { xs: 'flex-start', sm: 'center' }, py: 1.5 }}
      data-testid={`profile-row-${name}`}
    >
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: { xs: 0, sm: 160 } }}>
        {label}
      </Typography>
      <Typography sx={breakAnywhere ? { flex: 1, overflowWrap: 'anywhere' } : { flex: 1 }}>
        {value}
      </Typography>
      {onEdit === undefined ? null : (
        <Button size="small" data-testid={`profile-edit-${name}`} onClick={onEdit}>
          {t('settings.common.edit')}
        </Button>
      )}
    </Stack>
  )
}
