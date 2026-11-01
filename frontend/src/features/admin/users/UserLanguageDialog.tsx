/** Dialog zmiany języka konta przez administratora; błąd zapisu zostaje w dialogu. */

import { useState } from 'react'
import type { JSX } from 'react'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import { useUpdateUser } from '../queries'
import type { WdUser } from '../queries'
import { wdErrorKey } from '../wdClient'

import { UserLanguageField, accountLanguage } from './userLanguage'

export function UserLanguageDialog(props: {
  user: WdUser
  open: boolean
  onClose: () => void
}): JSX.Element {
  const { user, open, onClose } = props
  const { t } = useTranslation()
  const updateUser = useUpdateUser()
  const [language, setLanguage] = useState(accountLanguage(user.language))

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t('admin.users.language.title', { email: user.email })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {updateUser.isError ? (
            <Alert severity="error">{t(wdErrorKey(updateUser.error))}</Alert>
          ) : null}
          <UserLanguageField value={language} onChange={setLanguage} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('admin.common.cancel')}</Button>
        <Button
          variant="contained"
          data-testid="admin-user-language-save"
          loading={updateUser.isPending}
          onClick={() =>
            updateUser.mutate({ id: user.id, body: { language } }, { onSuccess: onClose })
          }
        >
          {t('admin.users.language.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
