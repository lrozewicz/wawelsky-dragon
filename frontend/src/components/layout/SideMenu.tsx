// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/dashboard/components/SideMenu.tsx (MIT). Zmiany: eksport named, bez SelectContent, nagłówek BrandLogo + app.name, przycisk zwijania (pełne/mini), szerokość 240/64 z przejściem, teksty i18n, stopka z OptionsMenu (onNavigate z useNavigate), formatowanie Prettier.
import Avatar from '@mui/material/Avatar'
import MuiDrawer, { drawerClasses } from '@mui/material/Drawer'
import Box from '@mui/material/Box'
import Divider from '@mui/material/Divider'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { styled } from '@mui/material/styles'
import ChevronLeftRoundedIcon from '@mui/icons-material/ChevronLeftRounded'
import ChevronRightRoundedIcon from '@mui/icons-material/ChevronRightRounded'
import { useNavigate } from '@tanstack/react-router'
import type { LinkProps } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { BrandLogo } from '../../theme/BrandLogo'
import type { Language } from '../../i18n'
import type { FeatureFlags } from '../../lib/featureFlags'

import { CardAlert } from './CardAlert'
import { MenuContent } from './MenuContent'
import { OptionsMenu } from './OptionsMenu'
import type { AppUser } from './types'

export const SIDE_MENU_WIDTH = 240
export const SIDE_MENU_MINI_WIDTH = 64

const Drawer = styled(MuiDrawer)({
  flexShrink: 0,
  boxSizing: 'border-box',
})

export function SideMenu(props: {
  pathname: string
  user: AppUser
  isSuperuser: boolean
  flags: FeatureFlags
  showModelsAlert: boolean
  docsUrl: string
  mini: boolean
  onToggleMini: () => void
  onLogout: () => void
  onLanguageChange: (language: Language) => void
}) {
  const {
    pathname,
    user,
    isSuperuser,
    flags,
    showModelsAlert,
    docsUrl,
    mini,
    onToggleMini,
    onLogout,
    onLanguageChange,
  } = props
  const { t } = useTranslation()
  const navigate = useNavigate()
  const width = mini ? SIDE_MENU_MINI_WIDTH : SIDE_MENU_WIDTH

  const handleNavigate = (to: string) => {
    // trasy dochodzą w E3-2…E3-6 — jedyne miejsce z rozluźnieniem typu `to`.
    navigate({ to: to as LinkProps['to'] })
  }

  return (
    <Drawer
      variant="permanent"
      sx={{
        width,
        display: { xs: 'none', md: 'block' },
        [`& .${drawerClasses.paper}`]: {
          width,
          boxSizing: 'border-box',
          backgroundColor: 'background.paper',
          borderRight: '1px solid',
          borderColor: 'divider',
          overflowX: 'hidden',
          transition: 'width 0.2s',
        },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          p: 1.5,
          justifyContent: mini ? 'center' : 'flex-start',
        }}
      >
        <BrandLogo />
        {mini ? null : (
          <Typography
            variant="subtitle1"
            noWrap
            sx={{ flexGrow: 1, ml: 1, fontSize: '0.95rem', fontWeight: 600 }}
          >
            {t('app.name')}
          </Typography>
        )}
        <IconButton onClick={onToggleMini} aria-label={mini ? t('nav.expand') : t('nav.collapse')}>
          {mini ? <ChevronRightRoundedIcon /> : <ChevronLeftRoundedIcon />}
        </IconButton>
      </Box>
      <Divider />
      <Box sx={{ overflow: 'auto', height: '100%', display: 'flex', flexDirection: 'column' }}>
        <MenuContent
          pathname={pathname}
          isSuperuser={isSuperuser}
          flags={flags}
          mini={mini}
          docsUrl={docsUrl}
        />
        <CardAlert show={showModelsAlert && !mini} />
      </Box>
      {/* W trybie mini pionowo (awatar nad menu): w 64 px awatar i przycisk obok siebie
          nie mieszczą się — przycisk wychodził poza rail i był ucięty (SC-E5-H8z-03). */}
      <Stack
        direction={mini ? 'column' : 'row'}
        sx={{
          p: mini ? 1 : 2,
          gap: 1,
          alignItems: 'center',
          justifyContent: mini ? 'center' : 'flex-start',
          borderTop: '1px solid',
          borderColor: 'divider',
        }}
      >
        <Avatar alt={user.name} src={user.avatarUrl} sx={{ width: 36, height: 36 }} />
        {mini ? null : (
          <Box sx={{ mr: 'auto', minWidth: 0 }}>
            <Typography
              variant="body2"
              noWrap
              title={user.name}
              sx={{ fontWeight: 500, lineHeight: '16px' }}
            >
              {user.name}
            </Typography>
            <Typography
              variant="caption"
              noWrap
              title={user.email}
              sx={{ color: 'text.secondary', display: 'block' }}
            >
              {user.email}
            </Typography>
          </Box>
        )}
        <OptionsMenu
          onLogout={onLogout}
          onLanguageChange={onLanguageChange}
          onNavigate={handleNavigate}
        />
      </Stack>
    </Drawer>
  )
}
