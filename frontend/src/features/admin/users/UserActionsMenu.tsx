/**
 * Menu akcji wiersza użytkownika (kontrakt WP E3-6c2 §4 i §T3 pkt 5): Szczegóły, Zmień hasło
 * (tylko konta lokalne), Nadaj/Odbierz administratora, Klucze API i Usuń. Wybór pozycji woła
 * `onAction(kind)` i zamyka menu. Pozycje dotyczące własnego konta są wyłączone — nie można
 * odebrać sobie admina ani usunąć własnego konta.
 */

import { useState } from 'react'
import type { JSX, MouseEvent } from 'react'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import IconButton from '@mui/material/IconButton'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import { useTranslation } from 'react-i18next'

import type { WdUser } from '../queries'

/** Rodzaje akcji wiersza (kontrakt §4); `role` obsługuje `UsersPage`, pozostałe dialogi T4. */
export type UserActionKind = 'details' | 'password' | 'role' | 'keys' | 'delete'

export type UserActionsMenuProps = {
  user: WdUser
  /** Identyfikator zalogowanego konta (`null`, gdy profilu jeszcze nie ma). */
  selfId: string | null
  onAction: (kind: UserActionKind) => void
}

export function UserActionsMenu(props: UserActionsMenuProps): JSX.Element {
  const { user, selfId, onAction } = props
  const { t } = useTranslation()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const isSelf = selfId !== null && user.id === selfId

  // Zamknięcie przed akcją: `onAction` otwiera dialog albo odpala mutację.
  function pick(kind: UserActionKind): void {
    setAnchor(null)
    onAction(kind)
  }

  return (
    <>
      <IconButton
        size="small"
        aria-label={t('admin.users.actions.open')}
        data-testid={`admin-user-actions-${user.id}`}
        onClick={(event: MouseEvent<HTMLElement>) => setAnchor(event.currentTarget)}
      >
        <MoreVertIcon fontSize="small" />
      </IconButton>

      <Menu anchorEl={anchor} open={anchor !== null} onClose={() => setAnchor(null)}>
        <MenuItem onClick={() => pick('details')}>{t('admin.users.actions.details')}</MenuItem>
        {user.auth_source === 'local' ? (
          <MenuItem onClick={() => pick('password')}>{t('admin.users.actions.password')}</MenuItem>
        ) : null}
        <MenuItem disabled={isSelf} onClick={() => pick('role')}>
          {t(
            user.is_superuser ? 'admin.users.actions.revokeAdmin' : 'admin.users.actions.makeAdmin',
          )}
        </MenuItem>
        <MenuItem onClick={() => pick('keys')}>{t('admin.users.actions.keys')}</MenuItem>
        <MenuItem disabled={isSelf} onClick={() => pick('delete')}>
          {t('admin.users.actions.delete')}
        </MenuItem>
      </Menu>
    </>
  )
}
