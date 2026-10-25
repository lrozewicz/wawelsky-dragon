// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/dashboard/components/OptionsMenu.tsx (MIT). Zmiany: eksport named, pozycje i18n (userMenu.*, language.*), podmenu języka (pl/en), akcje przez propsy onLogout/onLanguageChange/onNavigate, importy typów przez `import type`, formatowanie Prettier.
import * as React from 'react'
import { styled } from '@mui/material/styles'
import Divider, { dividerClasses } from '@mui/material/Divider'
import Menu from '@mui/material/Menu'
import MuiMenuItem from '@mui/material/MenuItem'
import { paperClasses } from '@mui/material/Paper'
import { listClasses } from '@mui/material/List'
import ListItemText from '@mui/material/ListItemText'
import ListItemIcon, { listItemIconClasses } from '@mui/material/ListItemIcon'
import LogoutRoundedIcon from '@mui/icons-material/LogoutRounded'
import MoreVertRoundedIcon from '@mui/icons-material/MoreVertRounded'
import { useTranslation } from 'react-i18next'

import type { Language } from '../../i18n'

import { MenuButton } from './MenuButton'

const MenuItem = styled(MuiMenuItem)({
  margin: '2px 0',
})

export function OptionsMenu(props: {
  onLogout: () => void
  onLanguageChange: (language: Language) => void
  onNavigate: (to: string) => void
}) {
  const { onLogout, onLanguageChange, onNavigate } = props
  const { t, i18n } = useTranslation()
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null)
  const [languageAnchorEl, setLanguageAnchorEl] = React.useState<null | HTMLElement>(null)
  const open = Boolean(anchorEl)
  const languageOpen = Boolean(languageAnchorEl)

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget)
  }

  const handleClose = () => {
    setAnchorEl(null)
  }

  const handleCloseAll = () => {
    setAnchorEl(null)
    setLanguageAnchorEl(null)
  }

  const currentLanguage = i18n.language.startsWith('en') ? 'en' : 'pl'

  return (
    <React.Fragment>
      <MenuButton
        aria-label={t('userMenu.open')}
        onClick={handleClick}
        sx={{ borderColor: 'transparent' }}
      >
        <MoreVertRoundedIcon />
      </MenuButton>
      <Menu
        anchorEl={anchorEl}
        id="user-menu"
        open={open}
        onClose={handleClose}
        transformOrigin={{ horizontal: 'right', vertical: 'top' }}
        anchorOrigin={{ horizontal: 'right', vertical: 'bottom' }}
        sx={{
          [`& .${listClasses.root}`]: {
            padding: '4px',
          },
          [`& .${paperClasses.root}`]: {
            padding: 0,
          },
          [`& .${dividerClasses.root}`]: {
            margin: '4px -4px',
          },
        }}
      >
        <MenuItem
          onClick={() => {
            onNavigate('/user-setting/profile')
            handleClose()
          }}
        >
          {t('userMenu.profile')}
        </MenuItem>
        <MenuItem
          onClick={() => {
            onNavigate('/user-setting/model')
            handleClose()
          }}
        >
          {t('userMenu.settings')}
        </MenuItem>
        <Divider />
        <MenuItem
          onClick={(event: React.MouseEvent<HTMLElement>) => {
            setLanguageAnchorEl(event.currentTarget)
            setAnchorEl(null)
          }}
        >
          {t('userMenu.language')}
        </MenuItem>
        <Divider />
        <MenuItem
          onClick={() => {
            onLogout()
            handleClose()
          }}
          sx={{
            [`& .${listItemIconClasses.root}`]: {
              ml: 'auto',
              minWidth: 0,
            },
          }}
        >
          <ListItemText>{t('userMenu.logout')}</ListItemText>
          <ListItemIcon>
            <LogoutRoundedIcon fontSize="small" />
          </ListItemIcon>
        </MenuItem>
      </Menu>
      <Menu
        anchorEl={languageAnchorEl}
        id="user-menu-language"
        open={languageOpen}
        onClose={handleCloseAll}
        transformOrigin={{ horizontal: 'right', vertical: 'top' }}
        anchorOrigin={{ horizontal: 'right', vertical: 'top' }}
      >
        <MenuItem
          selected={currentLanguage === 'pl'}
          onClick={() => {
            onLanguageChange('pl')
            handleCloseAll()
          }}
        >
          {t('language.pl')}
        </MenuItem>
        <MenuItem
          selected={currentLanguage === 'en'}
          onClick={() => {
            onLanguageChange('en')
            handleCloseAll()
          }}
        >
          {t('language.en')}
        </MenuItem>
      </Menu>
    </React.Fragment>
  )
}
