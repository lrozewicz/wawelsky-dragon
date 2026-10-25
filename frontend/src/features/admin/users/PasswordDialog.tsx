/**
 * Dialog zmiany hasła (kontrakt WP E3-6c2 §4 i §T4 pkt 2): pole „Nowe hasło” i zapis przez
 * `useSetPassword`. Hasło istnieje tylko dla kont `local` — dla pozostałych źródeł pokazujemy
 * komunikat `onlyLocal` i nie dajemy przycisku zapisu. Sukces zamyka dialog, a błąd mutacji
 * zostaje w dialogu jako `Alert` z komunikatem wg sluga (np. konto nie-lokalne = konflikt).
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useTranslation } from 'react-i18next'

import type { WdUser } from '../queries'
import { useSetPassword } from '../queries'
import { wdErrorKey } from '../wdClient'

export type PasswordDialogProps = {
  user: WdUser
  open: boolean
  onClose: () => void
}

export function PasswordDialog(props: PasswordDialogProps): JSX.Element {
  const { user, open, onClose } = props
  const { t } = useTranslation()
  const changePassword = useSetPassword()
  const [password, setPassword] = useState('')
  const isLocal = user.auth_source === 'local'

  /** Zamknięcie czyści pole i stan mutacji — kolejne otwarcie startuje od zera. */
  function close(): void {
    setPassword('')
    changePassword.reset()
    onClose()
  }

  function submit(): void {
    changePassword.mutate({ id: user.id, newPassword: password }, { onSuccess: close })
  }

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
      <DialogTitle>{t('admin.users.password.title')}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {changePassword.isError ? (
            <Alert severity="error">{t(wdErrorKey(changePassword.error))}</Alert>
          ) : null}

          {isLocal ? (
            <TextField
              autoFocus
              type="password"
              label={t('admin.users.password.new')}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          ) : (
            <Alert severity="info">{t('admin.users.password.onlyLocal')}</Alert>
          )}
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={close}>{t('admin.common.cancel')}</Button>
        {isLocal ? (
          <Button
            variant="contained"
            loading={changePassword.isPending}
            disabled={password === ''}
            onClick={submit}
          >
            {t('admin.users.password.submit')}
          </Button>
        ) : null}
      </DialogActions>
    </Dialog>
  )
}
