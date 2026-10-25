/**
 * Dialog usunięcia użytkownika (kontrakt WP E3-6c2 §4 i §T4 pkt 4): ostrzeżenie z e-mailem,
 * wybór trybu zasobów (transfer domyślnie / cascade) i potwierdzenie przez `useDeleteUser`.
 * Sukces zamyka dialog, błąd zostaje w dialogu jako `Alert` (np. ostatni administrator = konflikt).
 * Wspólny `components/ConfirmDialog` nie ma slotu na `RadioGroup`, dlatego budujemy okno wprost.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import FormControl from '@mui/material/FormControl'
import FormControlLabel from '@mui/material/FormControlLabel'
import FormLabel from '@mui/material/FormLabel'
import Radio from '@mui/material/Radio'
import RadioGroup from '@mui/material/RadioGroup'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import { useDeleteUser } from '../queries'
import type { WdUser } from '../queries'
import { wdErrorKey } from '../wdClient'

export type DeleteUserDialogProps = {
  user: WdUser
  open: boolean
  onClose: () => void
}

type DeleteMode = 'transfer' | 'cascade'

export function DeleteUserDialog(props: DeleteUserDialogProps): JSX.Element {
  const { user, open, onClose } = props
  const { t } = useTranslation()
  const deleteUser = useDeleteUser()
  const [mode, setMode] = useState<DeleteMode>('transfer')

  /** Zamknięcie wraca do trybu domyślnego i czyści stan mutacji. */
  function close(): void {
    setMode('transfer')
    deleteUser.reset()
    onClose()
  }

  function submit(): void {
    deleteUser.mutate({ id: user.id, mode }, { onSuccess: close })
  }

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="xs">
      <DialogTitle>{t('admin.users.delete.title')}</DialogTitle>

      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {deleteUser.isError ? (
            <Alert severity="error">{t(wdErrorKey(deleteUser.error))}</Alert>
          ) : null}

          <DialogContentText>
            {t('admin.users.delete.body', { email: user.email })}
          </DialogContentText>

          <FormControl>
            <FormLabel>{t('admin.users.delete.modeLabel')}</FormLabel>
            <RadioGroup
              value={mode}
              onChange={(event) => setMode(event.target.value as DeleteMode)}
            >
              <FormControlLabel
                value="transfer"
                control={<Radio />}
                label={t('admin.users.delete.mode.transfer')}
              />
              <FormControlLabel
                value="cascade"
                control={<Radio />}
                label={t('admin.users.delete.mode.cascade')}
              />
            </RadioGroup>
          </FormControl>
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={close}>{t('admin.common.cancel')}</Button>
        <Button color="error" variant="contained" loading={deleteUser.isPending} onClick={submit}>
          {t('admin.users.delete.confirm')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
