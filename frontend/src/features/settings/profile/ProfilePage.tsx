/**
 * Strona Profil w Ustawieniach (kontrakt WP E3-6c1 §T3, 08 §7.11): karta z wierszami
 * Nazwa / E-mail / Strefa czasowa / Hasło i małymi dialogami edycji. Profil czytamy z
 * `meQueryOptions()` (klucz `['me']` współdzielony z `AuthState`); wiersz hasła pokazujemy
 * tylko kontom lokalnym (`login_channel === 'password'`) — konta OIDC nie mają czego zmieniać.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { useQuery } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Divider from '@mui/material/Divider'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../../api/envelope'
import { meQueryOptions } from '../queries'

import { NameDialog } from './NameDialog'
import { PasswordDialog } from './PasswordDialog'
import { ProfileRow } from './ProfileRow'
import { TimezoneDialog } from './TimezoneDialog'

/** Który dialog edycji jest otwarty; `null` = żaden. */
type OpenDialog = 'name' | 'timezone' | 'password' | null

export function ProfilePage(): JSX.Element {
  const { t } = useTranslation()
  const me = useQuery(meQueryOptions())
  const [dialog, setDialog] = useState<OpenDialog>(null)

  if (me.isPending) {
    return <Skeleton variant="rounded" height={240} data-testid="profile-loading" />
  }

  if (me.isError) {
    return (
      <Alert severity="error">
        {me.error instanceof ApiError && me.error.message !== ''
          ? `${t('settings.error.title')}: ${me.error.message}`
          : t('settings.profile.loadError')}
      </Alert>
    )
  }

  const user = me.data

  return (
    <>
      <Card variant="outlined">
        <CardContent>
          <Stack divider={<Divider flexItem />}>
            {/* Nazwa bez spacji (do 60 znaków) łamie się także wewnątrz słowa — nie wychodzi
                poza kartę na 390 px (SC-E5-H9-07 k. 5); wzór: wiersz e-mail poniżej. */}
            <ProfileRow
              name="name"
              label={t('settings.profile.name')}
              value={user.nickname}
              breakAnywhere
              onEdit={() => setDialog('name')}
            />
            {/* Adres bywa dłuższy niż karta — łamie się także wewnątrz (SC-E5-H8z-03). */}
            <ProfileRow
              name="email"
              label={t('settings.profile.email')}
              value={user.email}
              breakAnywhere
            />
            <ProfileRow
              name="timezone"
              label={t('settings.profile.timezone')}
              value={user.timezone ?? t('settings.profile.timezoneEmpty')}
              onEdit={() => setDialog('timezone')}
            />
            {user.login_channel === 'password' ? (
              <ProfileRow
                name="password"
                label={t('settings.profile.password')}
                value={t('settings.profile.passwordMasked')}
                onEdit={() => setDialog('password')}
              />
            ) : null}
          </Stack>
        </CardContent>
      </Card>

      {dialog === 'name' ? (
        <NameDialog nickname={user.nickname} onClose={() => setDialog(null)} />
      ) : null}
      {dialog === 'timezone' ? (
        <TimezoneDialog timezone={user.timezone} onClose={() => setDialog(null)} />
      ) : null}
      {dialog === 'password' ? <PasswordDialog onClose={() => setDialog(null)} /> : null}
    </>
  )
}
