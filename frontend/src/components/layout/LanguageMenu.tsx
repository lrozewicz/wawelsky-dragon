import * as React from 'react'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import TranslateRoundedIcon from '@mui/icons-material/TranslateRounded'
import { useTranslation } from 'react-i18next'

import { resolveLanguage } from '../../i18n'
import type { Language } from '../../i18n'

import { MenuButton } from './MenuButton'

// Przełącznik języka interfejsu (używany w Header); stan rozwinięcia trzyma sam komponent.
export function LanguageMenu(props: { onLanguageChange: (language: Language) => void }) {
  const { onLanguageChange } = props
  const { t, i18n } = useTranslation()
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null)
  const open = Boolean(anchorEl)
  const currentLanguage = resolveLanguage(i18n.language)

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget)
  }

  const handleLanguage = (language: Language) => () => {
    onLanguageChange(language)
    setAnchorEl(null)
  }

  return (
    <React.Fragment>
      <MenuButton aria-label={t('userMenu.language')} onClick={handleClick}>
        <TranslateRoundedIcon />
      </MenuButton>
      <Menu
        anchorEl={anchorEl}
        id="language-menu"
        open={open}
        onClose={() => setAnchorEl(null)}
        transformOrigin={{ horizontal: 'right', vertical: 'top' }}
        anchorOrigin={{ horizontal: 'right', vertical: 'bottom' }}
      >
        <MenuItem selected={currentLanguage === 'pl'} onClick={handleLanguage('pl')}>
          {t('language.pl')}
        </MenuItem>
        <MenuItem selected={currentLanguage === 'en'} onClick={handleLanguage('en')}>
          {t('language.en')}
        </MenuItem>
      </Menu>
    </React.Fragment>
  )
}
