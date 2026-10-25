/**
 * Dialog zmiany hasła (kontrakt WP E3-6c1 §T3 p. 2): pola obecne / nowe / powtórz nowe, walidacja
 * zod (nowe ≥ 8 znaków, powtórka równa) i zapis TYLKO `password` + `new_password`. Sukces zamyka
 * dialog i pokazuje powiadomienie `settings.profile.passwordChanged`; błąd API zostaje w dialogu.
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

/** Minimalna długość nowego hasła (kontrakt §T3 p. 2). */
const PASSWORD_MIN = 8

export const passwordSchema = z
  .object({
    password: z.string(),
    newPassword: z
      .string()
      .min(PASSWORD_MIN, { error: 'settings.profile.passwordDialog.tooShort' }),
    repeat: z.string(),
  })
  .refine((values) => values.newPassword === values.repeat, {
    error: 'settings.profile.passwordDialog.mismatch',
    path: ['repeat'],
  })

export type PasswordDialogProps = {
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

export function PasswordDialog(props: PasswordDialogProps): React.JSX.Element {
  const { onClose } = props
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
    defaultValues: { password: '', newPassword: '', repeat: '' },
    validators: { onSubmit: passwordSchema },
    onSubmit: ({ value }) => {
      updateMe.mutate(
        { password: value.password, new_password: value.newPassword },
        {
          onSuccess: () => {
            show(t('settings.profile.passwordChanged'), {
              severity: 'success',
              autoHideDuration: 4000,
            })
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
      maxWidth="sm"
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
      <DialogTitle>{t('settings.profile.passwordDialog.title')}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {updateMe.isError ? (
            <Alert severity="error">
              {updateMe.error instanceof ApiError
                ? `${t('settings.error.title')}: ${updateMe.error.message}`
                : t('settings.error.title')}
            </Alert>
          ) : null}

          <form.Field name="password">
            {(field) => (
              <TextField
                autoFocus
                fullWidth
                type="password"
                autoComplete="current-password"
                label={t('settings.profile.passwordDialog.current')}
                value={field.state.value}
                onChange={(event) => field.handleChange(event.target.value)}
                slotProps={{ htmlInput: { 'data-testid': 'profile-password-current' } }}
              />
            )}
          </form.Field>

          <form.Field name="newPassword">
            {(field) => {
              const validationKey = errorKey(field.state.meta.errors)
              return (
                <TextField
                  fullWidth
                  type="password"
                  autoComplete="new-password"
                  label={t('settings.profile.passwordDialog.new')}
                  value={field.state.value}
                  error={validationKey !== undefined}
                  helperText={validationKey === undefined ? undefined : t(validationKey)}
                  onChange={(event) => field.handleChange(event.target.value)}
                  slotProps={{ htmlInput: { 'data-testid': 'profile-password-new' } }}
                />
              )
            }}
          </form.Field>

          <form.Field name="repeat">
            {(field) => {
              const validationKey = errorKey(field.state.meta.errors)
              return (
                <TextField
                  fullWidth
                  type="password"
                  autoComplete="new-password"
                  label={t('settings.profile.passwordDialog.repeat')}
                  value={field.state.value}
                  error={validationKey !== undefined}
                  helperText={validationKey === undefined ? undefined : t(validationKey)}
                  onChange={(event) => field.handleChange(event.target.value)}
                  slotProps={{ htmlInput: { 'data-testid': 'profile-password-repeat' } }}
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
          data-testid="profile-password-submit"
          loading={updateMe.isPending}
        >
          {t('settings.common.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
