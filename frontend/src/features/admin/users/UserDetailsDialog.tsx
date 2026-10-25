/**
 * Dialog szczegółów użytkownika (kontrakt WP E3-6c2 §4 i §T4 pkt 3): wyłącznie do odczytu.
 * Puste `timezone` pokazujemy jako kreskę, brak ostatniego logowania jako `never`, a daty w
 * formacie języka interfejsu. Etykiety bierzemy z istniejących kluczy `admin.users.*`.
 */

import type { JSX } from 'react'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import type { WdUser } from '../queries'

export type UserDetailsDialogProps = {
  user: WdUser
  open: boolean
  onClose: () => void
}

/** Data ISO 8601 w języku interfejsu; brak wartości to kreska. */
function formatDate(value: string | null, language: string): string {
  return value === null ? '—' : new Date(value).toLocaleString(language)
}

export function UserDetailsDialog(props: UserDetailsDialogProps): JSX.Element {
  const { user, open, onClose } = props
  const { t, i18n } = useTranslation()
  const language = i18n.language

  const rows: { label: string; value: string }[] = [
    { label: t('admin.users.col.email'), value: user.email },
    { label: t('admin.users.col.nickname'), value: user.nickname },
    {
      label: t('admin.users.col.role'),
      value: t(user.is_superuser ? 'admin.users.role.admin' : 'admin.users.role.user'),
    },
    {
      label: t('admin.users.col.source'),
      value: t(`admin.users.source.${user.auth_source}`, { defaultValue: user.auth_source }),
    },
    { label: t('admin.users.details.id'), value: user.id },
    { label: t('admin.users.details.language'), value: user.language },
    { label: t('admin.users.details.timezone'), value: user.timezone ?? '—' },
    {
      label: t('admin.users.details.lastLogin'),
      value:
        user.last_login_at === null
          ? t('admin.users.details.never')
          : formatDate(user.last_login_at, language),
    },
    { label: t('admin.users.col.created'), value: formatDate(user.created_at, language) },
    { label: t('admin.users.details.updated'), value: formatDate(user.updated_at, language) },
  ]

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t('admin.users.details.title')}</DialogTitle>

      <DialogContent>
        <Stack spacing={1.5} sx={{ mt: 1 }}>
          {rows.map((row) => (
            <Stack key={row.label} direction="row" spacing={2}>
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                {row.label}
              </Typography>
              <Typography variant="body2">{row.value}</Typography>
            </Stack>
          ))}
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>{t('admin.common.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}
