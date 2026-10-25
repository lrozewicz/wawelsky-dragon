/**
 * Dialog tworzenia użytkownika (kontrakt WP E3-6c2 §4 i §T3 pkt 6): e-mail (wymagany), hasło
 * początkowe i nazwa (opcjonalne) oraz checkbox administratora. Walidacja U11 (kontrakt K2):
 * przycisk pozostaje aktywny; pusty e-mail → `common.required`, błędny format → komunikat po
 * opuszczeniu pola i po próbie wysłania, fokus wraca na pole; unikalność sprawdza backend
 * (Alert wg sluga błędu, np. zajęty e-mail). Zmiana treści gasi komunikat. Sukces zamyka dialog
 * i czyści pola.
 */

import { useRef, useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import FormControlLabel from '@mui/material/FormControlLabel'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

import { isValidEmail } from '../../auth/authForm'
import { useCreateUser } from '../queries'
import { wdErrorKey } from '../wdClient'

export type CreateUserDialogProps = {
  open: boolean
  onClose: () => void
}

export function CreateUserDialog(props: CreateUserDialogProps): JSX.Element {
  const { open, onClose } = props
  const { t } = useTranslation()
  const createUser = useCreateUser()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [superuser, setSuperuser] = useState(false)
  // Walidacja U11 (kontrakt K2): `required` po próbie wysłania, `format` po opuszczeniu pola.
  const [emailError, setEmailError] = useState<'required' | 'format' | null>(null)
  const emailRef = useRef<HTMLInputElement>(null)

  const trimmedEmail = email.trim()
  const emailEmpty = trimmedEmail === ''
  // Format jak w formularzach logowania/rejestracji (T3); rozstrzygające sprawdzenie
  // unikalności (i formatu) robi backend.
  const emailFormatOk = isValidEmail(trimmedEmail)

  /** Zamknięcie czyści pola i stan mutacji — kolejne otwarcie startuje od zera (U7). */
  function close(): void {
    createUser.reset()
    setEmail('')
    setPassword('')
    setNickname('')
    setSuperuser(false)
    setEmailError(null)
    onClose()
  }

  function submit(): void {
    if (emailEmpty || !emailFormatOk) {
      setEmailError(emailEmpty ? 'required' : 'format')
      emailRef.current?.focus()
      return
    }
    createUser.mutate(
      {
        email: trimmedEmail,
        password: password === '' ? null : password,
        nickname: nickname === '' ? null : nickname,
        is_superuser: superuser,
      },
      { onSuccess: close },
    )
  }

  const emailHelperText =
    emailError === 'required'
      ? t('common.required')
      : emailError === 'format'
        ? t('auth.login.emailInvalid')
        : undefined

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
      <DialogTitle>{t('admin.users.create.title')}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {createUser.isError ? (
            <Alert severity="error">{t(wdErrorKey(createUser.error))}</Alert>
          ) : null}

          <TextField
            required
            autoFocus
            type="email"
            label={t('admin.users.create.email')}
            value={email}
            inputRef={emailRef}
            error={emailError !== null}
            helperText={emailHelperText}
            slotProps={{ inputLabel: { shrink: emailError !== null ? true : undefined } }}
            onChange={(event) => {
              setEmail(event.target.value)
              setEmailError(null)
            }}
            onBlur={() => {
              if (!emailEmpty && !emailFormatOk) setEmailError('format')
            }}
          />
          <TextField
            type="password"
            label={t('admin.users.create.password')}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <TextField
            label={t('admin.users.create.nickname')}
            value={nickname}
            onChange={(event) => setNickname(event.target.value)}
          />
          <FormControlLabel
            control={
              <Checkbox checked={superuser} onChange={(_event, checked) => setSuperuser(checked)} />
            }
            label={t('admin.users.create.superuser')}
          />
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={close}>{t('admin.common.cancel')}</Button>
        <Button
          variant="contained"
          data-testid="admin-create-user-submit"
          loading={createUser.isPending}
          onClick={submit}
        >
          {t('admin.users.create.submit')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
