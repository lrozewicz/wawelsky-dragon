import { type JSX } from 'react'
import Box from '@mui/material/Box'
import Link from '@mui/material/Link'
import { useMatches, useNavigate, useRouterState } from '@tanstack/react-router'
import type { LinkProps } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { changeLanguage } from '../../i18n'
import type { Language } from '../../i18n'
import { getEnv, getFeatureFlags } from '../../app/env'
// Augmentacja typów tras (`staticData.fullBleed`) — potrzebna dla `useMatches()`.
import '../../app/routerTypes'

import { AppNavbar } from './AppNavbar'
import { Header } from './Header'
import { SideMenu } from './SideMenu'
import { useSideMenuMini } from './useSideMenuMini'
import type { AppUser } from './types'

export type AppLayoutProps = {
  user: AppUser
  isSuperuser: boolean
  showModelsAlert: boolean
  onLogout: () => void
  onLanguageChange?: (language: Language) => void
  children: React.ReactNode
}

// Powłoka zalogowanej aplikacji: skip-link, menu boczne (desktop), navbar (mobile),
// nagłówek z okruszkami i `main`. Złożenie wzorowane na szablonie `dashboard` (Dashboard.tsx, MIT).
export function AppLayout(props: AppLayoutProps): JSX.Element {
  const { user, isSuperuser, showModelsAlert, onLogout, onLanguageChange, children } = props
  const { t } = useTranslation()
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  // Trasy pełnoekranowe (np. czat) wymuszają zwinięte menu boczne.
  const autoMini = useMatches().some((match) => match.staticData.fullBleed === true)
  const { mini, toggle } = useSideMenuMini(autoMini)
  const flags = getFeatureFlags()
  const docsUrl = getEnv().DOCS_URL
  const navigate = useNavigate()
  const handleLanguageChange = onLanguageChange ?? changeLanguage

  const handleNavigate = (to: string) => {
    // trasy dochodzą w E3-2…E3-6 — jedyne miejsce z rozluźnieniem typu `to`.
    navigate({ to: to as LinkProps['to'] })
  }

  return (
    <Box sx={{ display: 'flex' }}>
      <Link
        href="#main-content"
        sx={{
          position: 'absolute',
          top: 0,
          left: 0,
          zIndex: (theme) => theme.zIndex.tooltip + 1,
          m: 1,
          px: 2,
          py: 1,
          borderRadius: 1,
          bgcolor: 'background.paper',
          color: 'text.primary',
          // Widoczny wyłącznie po fokusie (kolejność tabulacji bez zmian).
          transform: 'translateY(-300%)',
          '&:focus': { transform: 'translateY(0)' },
        }}
      >
        {t('app.skipToContent')}
      </Link>
      <SideMenu
        pathname={pathname}
        user={user}
        isSuperuser={isSuperuser}
        flags={flags}
        showModelsAlert={showModelsAlert}
        docsUrl={docsUrl}
        mini={mini}
        onToggleMini={toggle}
        onLogout={onLogout}
        onLanguageChange={handleLanguageChange}
      />
      <AppNavbar
        pathname={pathname}
        user={user}
        isSuperuser={isSuperuser}
        flags={flags}
        showModelsAlert={showModelsAlert}
        docsUrl={docsUrl}
        onLogout={onLogout}
        onLanguageChange={handleLanguageChange}
        onNavigate={handleNavigate}
      />
      <Box
        component="main"
        id="main-content"
        tabIndex={-1}
        sx={{ flexGrow: 1, minWidth: 0, mt: { xs: 8, md: 0 } }}
      >
        <Header pathname={pathname} onLanguageChange={handleLanguageChange} />
        {children}
      </Box>
    </Box>
  )
}
