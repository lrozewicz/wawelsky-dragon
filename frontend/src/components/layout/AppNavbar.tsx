// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/dashboard/components/AppNavbar.tsx (MIT). Zmiany: eksport named, bez `CustomIcon`/`CustomIcon` z szablonu — BrandLogo (size 24) + app.name jako `component="span"` (jeden h1 na stronę), stan `open` wewnątrz komponentu, hamburger z aria-label nav.openMenu, propsy powłoki (C5) przekazywane do SideMenuMobile, import typu przez `import type`, formatowanie Prettier.
import * as React from 'react'
import AppBar from '@mui/material/AppBar'
import Stack from '@mui/material/Stack'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import MenuRoundedIcon from '@mui/icons-material/MenuRounded'
import { useTranslation } from 'react-i18next'

import { BrandLogo } from '../../theme/BrandLogo'
import ColorModeIconDropdown from '../../theme/ColorModeIconDropdown'
import type { Language } from '../../i18n'
import type { FeatureFlags } from '../../lib/featureFlags'

import { MenuButton } from './MenuButton'
import { SideMenuMobile } from './SideMenuMobile'
import type { AppUser } from './types'

export function AppNavbar(props: {
  pathname: string
  user: AppUser
  isSuperuser: boolean
  flags: FeatureFlags
  showModelsAlert: boolean
  docsUrl: string
  onLogout: () => void
  onLanguageChange: (language: Language) => void
  onNavigate: (to: string) => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = React.useState(false)
  const toggleDrawer = (newOpen: boolean) => () => {
    setOpen(newOpen)
  }

  return (
    <AppBar
      position="fixed"
      sx={{
        display: { xs: 'flex', md: 'none' },
        boxShadow: 0,
        bgcolor: 'background.paper',
        // AppBar domyślnie ustawia color="primary" (jasny tekst); logo dziedziczy currentColor,
        // więc na jasnym tle potrzebny jest kolor tekstu motywu.
        color: 'text.primary',
        backgroundImage: 'none',
        borderBottom: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Toolbar variant="regular">
        <Stack direction="row" sx={{ alignItems: 'center', flexGrow: 1, width: '100%', gap: 0.5 }}>
          {/* `minWidth: 0` + `overflow: hidden` — tytuł skraca się wielokropkiem zamiast wypychać
              przycisk motywu i hamburger poza okno przy 312/320 px (SC-E67-05). */}
          <Stack
            direction="row"
            spacing={1}
            sx={{ alignItems: 'center', mr: 'auto', minWidth: 0, overflow: 'hidden' }}
          >
            <BrandLogo size={24} />
            {/* `noWrap` — zawinięta nazwa aplikacji rozdymała baner do 2 linii (73 px na 390 px)
                nad treścią rezerwowaną przez `mt: { xs: 8 }` w `AppLayout` (SC-E5-H8c-05). */}
            <Typography
              variant="h4"
              component="span"
              noWrap
              sx={{ color: 'text.primary', minWidth: 0 }}
            >
              {t('app.name')}
            </Typography>
          </Stack>
          <ColorModeIconDropdown />
          <MenuButton aria-label={t('nav.openMenu')} onClick={toggleDrawer(true)}>
            <MenuRoundedIcon />
          </MenuButton>
          <SideMenuMobile open={open} onClose={toggleDrawer(false)} {...props} />
        </Stack>
      </Toolbar>
    </AppBar>
  )
}
