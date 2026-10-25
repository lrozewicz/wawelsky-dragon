import type { JSX } from 'react'
import { Outlet, createFileRoute, useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { api, apiCall } from '../../api/client'
import type { components } from '../../api/schema.gen'
import { requireSession } from '../../app/guards'
import { AppLayout } from '../../components/layout/AppLayout'
import type { AppUser } from '../../components/layout/types'
import { useShowModelsAlert } from '../../features/models/queries'
import useNotifications from '../../hooks/useNotifications/useNotifications'
import { changeLanguage } from '../../i18n'
import type { Language } from '../../i18n'

export const Route = createFileRoute('/_app')({
  beforeLoad: ({ context, location }) => requireSession(context.auth, location),
  component: AppShell,
})

// Powłoka zalogowanej aplikacji zasilana stanem sesji z kontekstu routera (08 §4.3, §5.3).
function AppShell(): JSX.Element | null {
  const { auth } = Route.useRouteContext()
  const { t } = useTranslation()
  const { show } = useNotifications()
  const navigate = useNavigate()
  const showModelsAlert = useShowModelsAlert()
  const user = auth.user

  // Po guardzie `requireSession` użytkownik zawsze istnieje; to domknięcie typu.
  if (user === null) return null

  const appUser: AppUser = { name: user.nickname, email: user.email }
  if (user.avatar) appUser.avatarUrl = user.avatar

  const handleLanguageChange = (language: Language): void => {
    // Backend przyjmuje częściowe ciało (`update_profile` bierze tylko obecne klucze), ale
    // wygenerowany typ `UpdateMeRequest` wymaga wszystkich pól — stąd lokalne rzutowanie.
    const body = { language } as unknown as components['schemas']['UpdateMeRequest']
    void apiCall(api.PATCH('/api/v1/users/me', { body }))
      .then(() => changeLanguage(language))
      .catch(() => {
        show(t('userMenu.languageError'), { key: 'userMenu.languageError', severity: 'error' })
      })
  }

  // Konto OIDC: po zakończeniu sesji lokalnej przechodzimy na `logout_url` dostawcy tożsamości (R10).
  const handleLogout = (): void => {
    void auth.logout().then((logoutUrl) => {
      if (logoutUrl !== null) window.location.assign(logoutUrl)
      else void navigate({ to: '/login' })
    })
  }

  return (
    <AppLayout
      user={appUser}
      isSuperuser={auth.hasRole('superuser')}
      showModelsAlert={showModelsAlert}
      onLogout={handleLogout}
      onLanguageChange={handleLanguageChange}
    >
      <Outlet />
    </AppLayout>
  )
}
