// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/dashboard/components/SideMenuMobile.tsx (MIT). Zmiany: eksport named, propsy zamiast `toggleDrawer` (`open`/`onClose`) oraz kontekst powłoki (pathname/isSuperuser/flags/docsUrl/onLogout/onLanguageChange/onNavigate), przycisk zamknięcia zamiast powiadomień (aria-label nav.closeMenu), MenuContent z i18n, CardAlert z propem show, przycisk Wyloguj (i18n), LanguageMenu w stopce, formatowanie Prettier.
import Avatar from '@mui/material/Avatar'
import Button from '@mui/material/Button'
import Divider from '@mui/material/Divider'
import Drawer, { drawerClasses } from '@mui/material/Drawer'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import CloseRoundedIcon from '@mui/icons-material/CloseRounded'
import LogoutRoundedIcon from '@mui/icons-material/LogoutRounded'
import { useTranslation } from 'react-i18next'

import type { Language } from '../../i18n'
import type { FeatureFlags } from '../../lib/featureFlags'

import { CardAlert } from './CardAlert'
import { LanguageMenu } from './LanguageMenu'
import { MenuButton } from './MenuButton'
import { MenuContent } from './MenuContent'
import type { AppUser } from './types'

export function SideMenuMobile(props: {
  open: boolean
  onClose: () => void
  pathname: string
  user: AppUser
  isSuperuser: boolean
  flags: FeatureFlags
  showModelsAlert: boolean
  docsUrl: string
  onLogout: () => void
  onLanguageChange: (language: Language) => void
  // `onNavigate` należy do wspólnego API powłoki (C5); w wersji mobilnej pozycje
  // nawigują przez NavLink, więc prop jest przyjmowany i przekazywany dalej przez AppNavbar.
  onNavigate: (to: string) => void
}) {
  const {
    open,
    onClose,
    pathname,
    user,
    isSuperuser,
    flags,
    showModelsAlert,
    docsUrl,
    onLogout,
    onLanguageChange,
  } = props
  const { t } = useTranslation()

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      sx={{
        zIndex: (theme) => theme.zIndex.drawer + 1,
        [`& .${drawerClasses.paper}`]: {
          backgroundImage: 'none',
          backgroundColor: 'background.paper',
        },
      }}
    >
      <Stack sx={{ maxWidth: '70dvw', height: '100%' }}>
        <Stack direction="row" sx={{ p: 2, pb: 0, gap: 1 }}>
          <Stack direction="row" sx={{ gap: 1, alignItems: 'center', flexGrow: 1, p: 1 }}>
            <Avatar alt={user.name} src={user.avatarUrl} sx={{ width: 24, height: 24 }} />
            <Typography component="p" variant="h6">
              {user.name}
            </Typography>
          </Stack>
          <MenuButton aria-label={t('nav.closeMenu')} onClick={onClose}>
            <CloseRoundedIcon />
          </MenuButton>
        </Stack>
        <Divider />
        <Stack sx={{ flexGrow: 1 }}>
          <MenuContent
            pathname={pathname}
            isSuperuser={isSuperuser}
            flags={flags}
            mini={false}
            docsUrl={docsUrl}
            onNavigate={onClose}
          />
          <Divider />
        </Stack>
        <CardAlert show={showModelsAlert} />
        <Stack direction="row" sx={{ p: 2, gap: 1, alignItems: 'center' }}>
          <Button
            variant="outlined"
            fullWidth
            startIcon={<LogoutRoundedIcon />}
            onClick={onLogout}
            sx={{ flexGrow: 1 }}
          >
            {t('userMenu.logout')}
          </Button>
          <LanguageMenu onLanguageChange={onLanguageChange} />
        </Stack>
      </Stack>
    </Drawer>
  )
}
