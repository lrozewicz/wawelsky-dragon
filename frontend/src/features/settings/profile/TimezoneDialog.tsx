/**
 * Dialog zmiany strefy czasowej (kontrakt WP E3-6c1 §T3 p. 1, 4, 6): pole z podpowiedziami stref
 * IANA (`Intl.supportedValuesOf('timeZone')`) w sekcji „Zaawansowane” (08 §8: ADV). Wysyła
 * TYLKO pole `timezone`; sukces zamyka dialog i pokazuje `settings.profile.saved`.
 */

import * as React from 'react'
import { useState } from 'react'
import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Autocomplete from '@mui/material/Autocomplete'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import useNotifications from '../../../hooks/useNotifications/useNotifications'
import { useUpdateMe } from '../queries'

/**
 * Strefy IANA do podpowiedzi. `Intl.supportedValuesOf` jest w ES2022, ale gdyby środowisko go
 * nie miało, zostaje krótka lista z kilkoma najczęstszymi strefami (kontrakt §T3, „Wskazówki”).
 */
const TIMEZONE_OPTIONS: readonly string[] =
  typeof Intl.supportedValuesOf === 'function'
    ? Intl.supportedValuesOf('timeZone')
    : ['UTC', 'Europe/Warsaw', 'Europe/London', 'America/New_York', 'Asia/Tokyo']

export type TimezoneDialogProps = {
  /** Strefa bieżąca; `null` = „Nie ustawiono” (pole startuje puste). */
  timezone: string | null
  onClose: () => void
}

export function TimezoneDialog(props: TimezoneDialogProps): React.JSX.Element {
  const { timezone, onClose } = props
  const { t } = useTranslation()
  const { show } = useNotifications()
  const updateMe = useUpdateMe()
  const reset = updateMe.reset
  const [value, setValue] = useState(timezone ?? '')

  // Błąd mutacji nie może przetrwać odmontowania dialogu (kontrakt WP E3-H2b §C3) — czyszczenie
  // stanu także przy zniknięciu komponentu (zmiana zakładki Ustawień, wzór: `CreateKeyDialog`).
  React.useEffect(() => () => reset(), [reset])

  /** Zamknięcie czyści stan mutacji — kolejne otwarcie startuje od zera. */
  function close(): void {
    updateMe.reset()
    onClose()
  }

  function submit(): void {
    updateMe.mutate(
      { timezone: value.trim() },
      {
        onSuccess: () => {
          show(t('settings.profile.saved'), { severity: 'success', autoHideDuration: 4000 })
          close()
        },
      },
    )
  }

  return (
    <Dialog
      open
      onClose={close}
      fullWidth
      maxWidth="sm"
      slotProps={{
        paper: {
          component: 'form',
          onSubmit: (event: React.SubmitEvent<HTMLFormElement>) => {
            event.preventDefault()
            submit()
          },
        },
      }}
    >
      <DialogTitle>{t('settings.profile.timezoneDialog.title')}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {updateMe.isError ? (
            <Alert severity="error">
              {updateMe.error instanceof ApiError
                ? `${t('settings.error.title')}: ${updateMe.error.message}`
                : t('settings.error.title')}
            </Alert>
          ) : null}

          <Accordion disableGutters defaultExpanded>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography>{t('settings.profile.timezoneDialog.advanced')}</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Autocomplete
                freeSolo
                fullWidth
                options={TIMEZONE_OPTIONS}
                inputValue={value}
                onInputChange={(_event, next) => setValue(next)}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    autoFocus
                    label={t('settings.profile.timezone')}
                    helperText={t('settings.profile.timezoneDialog.hint')}
                  />
                )}
              />
            </AccordionDetails>
          </Accordion>
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={close}>{t('settings.common.cancel')}</Button>
        <Button
          type="submit"
          variant="contained"
          data-testid="profile-timezone-submit"
          loading={updateMe.isPending}
        >
          {t('settings.common.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
