/**
 * Pasek zapisu konfiguracji datasetu (U11): „Anuluj” i „Zapisz” przyklejone do dołu karty.
 * Wydzielone z `ConfigurationTab.tsx` przez limit rozmiaru pliku (wzór: `useSaveWithApply.ts`).
 */
import type { JSX } from 'react'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import { DisabledReason, describedBy } from '../../../components/DisabledReason'

export function SaveFooter(props: {
  onCancel: () => void
  onSubmit: () => void
  /** „Zapisz” wyłączony bez zmian albo przy błędzie walidacji. */
  disabled: boolean
  /** Powód nieaktywnego „Zapisz” (SC-V12-08) pod przyciskiem; `null` = brak tekstu. */
  reason: string | null
  loading: boolean
}): JSX.Element {
  const { t } = useTranslation()
  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{
        position: 'sticky',
        bottom: 0,
        justifyContent: 'flex-end',
        flexWrap: 'wrap',
        rowGap: 0.5,
        bgcolor: 'background.paper',
        borderTop: 1,
        borderColor: 'divider',
        py: 2,
      }}
    >
      <DisabledReason id="config-save-reason" reason={props.reason} />
      <Button onClick={props.onCancel}>{t('common.cancel')}</Button>
      <Button
        variant="contained"
        // U11: brak zmian wyłącza, błędy ujawnia klik (K2); mousedown bez przejęcia fokusu (T9).
        disabled={props.disabled}
        loading={props.loading}
        onClick={props.onSubmit}
        onMouseDown={(event) => event.preventDefault()}
        aria-describedby={describedBy('config-save-reason', props.reason)}
      >
        {t('datasets.config.save')}
      </Button>
    </Stack>
  )
}
