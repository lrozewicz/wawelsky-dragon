// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/shared-theme/ColorModeIconDropdown.tsx (MIT). Zmiany: import typu (type IconButtonOwnProps); etykiety menu i aria-label przez i18n (t('theme.*')); formatowanie Prettier.
import * as React from 'react'
import DarkModeIcon from '@mui/icons-material/DarkModeRounded'
import LightModeIcon from '@mui/icons-material/LightModeRounded'
import Box from '@mui/material/Box'
import IconButton, { type IconButtonOwnProps } from '@mui/material/IconButton'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import { useColorScheme } from '@mui/material/styles'
import { useTranslation } from 'react-i18next'

export default function ColorModeIconDropdown(props: IconButtonOwnProps) {
  const { t } = useTranslation()
  const { mode, systemMode, setMode } = useColorScheme()
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null)
  const open = Boolean(anchorEl)
  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget)
  }
  const handleClose = () => {
    setAnchorEl(null)
  }
  const handleMode = (targetMode: 'system' | 'light' | 'dark') => () => {
    setMode(targetMode)
    handleClose()
  }
  if (!mode) {
    return (
      <Box
        data-screenshot="toggle-mode"
        sx={(theme) => ({
          verticalAlign: 'bottom',
          display: 'inline-flex',
          width: '2.25rem',
          height: '2.25rem',
          borderRadius: (theme.vars || theme).shape.borderRadius,
          border: '1px solid',
          borderColor: (theme.vars || theme).palette.divider,
        })}
      />
    )
  }
  const resolvedMode = (systemMode || mode) as 'light' | 'dark'
  const icon = {
    light: <LightModeIcon />,
    dark: <DarkModeIcon />,
  }[resolvedMode]
  return (
    <React.Fragment>
      <IconButton
        data-screenshot="toggle-mode"
        onClick={handleClick}
        disableRipple
        size="small"
        aria-label={t('theme.mode')}
        aria-controls={open ? 'color-scheme-menu' : undefined}
        aria-haspopup="true"
        aria-expanded={open ? 'true' : undefined}
        {...props}
      >
        {icon}
      </IconButton>
      <Menu
        anchorEl={anchorEl}
        id="account-menu"
        open={open}
        onClose={handleClose}
        onClick={handleClose}
        slotProps={{
          paper: {
            variant: 'outlined',
            elevation: 0,
            sx: {
              my: '4px',
            },
          },
        }}
        transformOrigin={{ horizontal: 'right', vertical: 'top' }}
        anchorOrigin={{ horizontal: 'right', vertical: 'bottom' }}
      >
        <MenuItem selected={mode === 'system'} onClick={handleMode('system')}>
          {t('theme.system')}
        </MenuItem>
        <MenuItem selected={mode === 'light'} onClick={handleMode('light')}>
          {t('theme.light')}
        </MenuItem>
        <MenuItem selected={mode === 'dark'} onClick={handleMode('dark')}>
          {t('theme.dark')}
        </MenuItem>
      </Menu>
    </React.Fragment>
  )
}
