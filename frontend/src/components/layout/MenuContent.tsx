// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/dashboard/components/MenuContent.tsx (MIT). Zmiany: eksport named, pozycje z NAV_ITEMS (i18n), aktywna pozycja wg isNavItemActive (aria-current), tryb mini (tylko ikona + Tooltip), pozycja Pomoc (link zewnętrzny) renderowana warunkowo, formatowanie Prettier.
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import HelpOutlineRoundedIcon from '@mui/icons-material/HelpOutlineRounded'
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded'
import { useTranslation } from 'react-i18next'

import type { FeatureFlags } from '../../lib/featureFlags'

import type { NavItem } from './navItems'
import { isNavItemActive, visibleNavItems } from './navItems'
import { NavLink } from './RouterListItemButton'

export function MenuContent(props: {
  pathname: string
  isSuperuser: boolean
  flags: FeatureFlags
  mini: boolean
  docsUrl: string
  onNavigate?: () => void
}) {
  const { pathname, isSuperuser, flags, mini, docsUrl, onNavigate } = props
  const { t } = useTranslation()

  const items = visibleNavItems({ isSuperuser, flags })
  const mainItems = items.filter((item) => item.group === 'main')
  const bottomItems = items.filter((item) => item.group === 'bottom')

  const renderItem = (item: NavItem) => {
    const label = t(item.labelKey)
    const active = isNavItemActive(item, pathname)
    const button = (
      <NavLink
        to={item.to}
        selected={active}
        aria-current={active ? 'page' : undefined}
        aria-label={mini ? label : undefined}
        onClick={onNavigate}
        sx={mini ? { justifyContent: 'center' } : undefined}
      >
        <ListItemIcon sx={mini ? { minWidth: 0, justifyContent: 'center' } : undefined}>
          {item.icon}
        </ListItemIcon>
        {mini ? null : <ListItemText primary={label} />}
      </NavLink>
    )

    return mini ? (
      <Tooltip title={label} placement="right">
        {button}
      </Tooltip>
    ) : (
      button
    )
  }

  const helpItem =
    docsUrl === '' ? null : (
      <ListItem disablePadding sx={{ display: 'block' }}>
        {mini ? (
          <Tooltip title={t('nav.help')} placement="right">
            <ListItemButton
              component="a"
              href={docsUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={t('nav.help')}
              onClick={onNavigate}
              sx={{ justifyContent: 'center' }}
            >
              <ListItemIcon sx={{ minWidth: 0, justifyContent: 'center' }}>
                <HelpOutlineRoundedIcon />
              </ListItemIcon>
            </ListItemButton>
          </Tooltip>
        ) : (
          <ListItemButton
            component="a"
            href={docsUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={onNavigate}
          >
            <ListItemIcon>
              <HelpOutlineRoundedIcon />
            </ListItemIcon>
            <ListItemText primary={t('nav.help')} />
            <OpenInNewRoundedIcon fontSize="small" />
          </ListItemButton>
        )}
      </ListItem>
    )

  return (
    <Stack
      component="nav"
      aria-label={t('nav.main')}
      sx={{ flexGrow: 1, p: mini ? 0.5 : 1, justifyContent: 'space-between' }}
    >
      <List dense>
        {mainItems.map((item) => (
          <ListItem key={item.key} disablePadding sx={{ display: 'block' }}>
            {renderItem(item)}
          </ListItem>
        ))}
      </List>
      <List dense>
        {bottomItems.map((item) => (
          <ListItem key={item.key} disablePadding sx={{ display: 'block' }}>
            {renderItem(item)}
          </ListItem>
        ))}
        {helpItem}
      </List>
    </Stack>
  )
}
