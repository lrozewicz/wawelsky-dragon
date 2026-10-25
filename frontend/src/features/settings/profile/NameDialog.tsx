/**
 * Dialog zmiany nazwy (kontrakt WP E3-6c1 §T3 p. 1, 4, 6): jedno pole „Nazwa” z walidacją zod
 * (wymagane po trim, ≤ 128 znaków) i zapisem TYLKO pola `nickname`. Sukces zamyka dialog
 * i pokazuje powiadomienie `settings.profile.saved`; błąd API zostaje w dialogu jako `Alert`.
 */

import * as React from 'react'
import { useForm } from '@tanstack/react-form'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'
import { z } from 'zod'

import { ApiError } from '../../../api/envelope'
import useNotifications from '../../../hooks/useNotifications/useNotifications'
import { useUpdateMe } from '../queries'

/** Maksymalna długość nazwy przyjmowana przez backend (kontrakt §0). */
const NAME_MAX = 128

export const nameSchema = z.object({
  nickname: z
    .string()
    .trim()
    .min(1, { error: 'settings.profile.nameRequired' })
    .max(NAME_MAX, { error: 'settings.profile.nameTooLong' }),
})

export type NameDialogProps = {
  /** Nazwa bieżąca — punkt startowy pola. */
  nickname: string
  onClose: () => void
}

/** Klucz i18n pierwszego błędu pola; zod przez Standard Schema zwraca `{message}` (jak w authForm). */
function errorKey(errors: readonly unknown[]): string | undefined {
  const issue = errors.find(
    (entry): entry is { message: string } =>
      typeof entry === 'object' &&
      entry !== null &&
      'message' in entry &&
      typeof entry.message === 'string',
  )
  return issue?.message
}

export function NameDialog(props: NameDialogProps): React.JSX.Element {
  const { nickname, onClose } = props
  const { t } = useTranslation()
  const { show } = useNotifications()
  const updateMe = useUpdateMe()
  const reset = updateMe.reset

  // Błąd mutacji nie może przetrwać odmontowania dialogu (kontrakt WP E3-H2b §C3) — czyszczenie
  // stanu także przy zniknięciu komponentu (zmiana zakładki Ustawień, wzór: `CreateKeyDialog`).
  React.useEffect(() => () => reset(), [reset])

  /** Zamknięcie czyści stan mutacji — kolejne otwarcie startuje od zera. */
  function close(): void {
    updateMe.reset()
    onClose()
  }

  const form = useForm({
    defaultValues: { nickname },
    validators: { onSubmit: nameSchema },
    onSubmit: ({ value }) => {
      updateMe.mutate(
        { nickname: value.nickname.trim() },
        {
          onSuccess: () => {
            show(t('settings.profile.saved'), { severity: 'success', autoHideDuration: 4000 })
            close()
          },
        },
      )
    },
  })

  return (
    <Dialog
      open
      onClose={close}
      fullWidth
      maxWidth="xs"
      slotProps={{
        paper: {
          component: 'form',
          onSubmit: (event: React.SubmitEvent<HTMLFormElement>) => {
            event.preventDefault()
            void form.handleSubmit()
          },
        },
      }}
    >
      <DialogTitle>{t('settings.profile.nameDialog.title')}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {updateMe.isError ? (
            <Alert severity="error">
              {updateMe.error instanceof ApiError
                ? `${t('settings.error.title')}: ${updateMe.error.message}`
                : t('settings.error.title')}
            </Alert>
          ) : null}

          <form.Field name="nickname">
            {(field) => {
              const validationKey = errorKey(field.state.meta.errors)
              return (
                <TextField
                  autoFocus
                  required
                  fullWidth
                  margin="dense"
                  label={t('settings.profile.name')}
                  value={field.state.value}
                  error={validationKey !== undefined}
                  helperText={validationKey === undefined ? undefined : t(validationKey)}
                  onChange={(event) => field.handleChange(event.target.value)}
                  slotProps={{ htmlInput: { 'data-testid': 'profile-name-input' } }}
                />
              )
            }}
          </form.Field>
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={close}>{t('settings.common.cancel')}</Button>
        <Button
          type="submit"
          variant="contained"
          data-testid="profile-name-submit"
          loading={updateMe.isPending}
        >
          {t('settings.common.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
