import type { ReactElement } from 'react'
import HomeRoundedIcon from '@mui/icons-material/HomeRounded'
import LibraryBooksRoundedIcon from '@mui/icons-material/LibraryBooksRounded'
import ChatRoundedIcon from '@mui/icons-material/ChatRounded'
import SearchRoundedIcon from '@mui/icons-material/SearchRounded'
import AccountTreeRoundedIcon from '@mui/icons-material/AccountTreeRounded'
import PsychologyRoundedIcon from '@mui/icons-material/PsychologyRounded'
import FolderRoundedIcon from '@mui/icons-material/FolderRounded'
import SettingsRoundedIcon from '@mui/icons-material/SettingsRounded'
import AdminPanelSettingsRoundedIcon from '@mui/icons-material/AdminPanelSettingsRounded'

import type { FeatureFlags } from '../../lib/featureFlags'

export type NavItemKey =
  | 'home'
  | 'datasets'
  | 'chat'
  | 'search'
  | 'agent'
  | 'memory'
  | 'files'
  | 'settings'
  | 'admin'
  | 'help'

export type NavItem = {
  key: NavItemKey
  labelKey: string
  to: string
  match: readonly string[]
  group: 'main' | 'bottom'
  icon: ReactElement
}

// Kolejność jest częścią kontraktu (C5) — nie zmieniać.
export const NAV_ITEMS: readonly NavItem[] = [
  {
    key: 'home',
    labelKey: 'nav.home',
    to: '/',
    match: ['/'],
    group: 'main',
    icon: <HomeRoundedIcon />,
  },
  {
    key: 'datasets',
    labelKey: 'nav.datasets',
    to: '/datasets',
    match: ['/datasets', '/dataset', '/chunk'],
    group: 'main',
    icon: <LibraryBooksRoundedIcon />,
  },
  {
    key: 'chat',
    labelKey: 'nav.chat',
    to: '/chats',
    match: ['/chats', '/chat'],
    group: 'main',
    icon: <ChatRoundedIcon />,
  },
  {
    key: 'search',
    labelKey: 'nav.search',
    to: '/searches',
    match: ['/searches', '/search'],
    group: 'main',
    icon: <SearchRoundedIcon />,
  },
  {
    key: 'agent',
    labelKey: 'nav.agent',
    to: '/agents',
    match: ['/agents', '/agent'],
    group: 'main',
    icon: <AccountTreeRoundedIcon />,
  },
  {
    key: 'memory',
    labelKey: 'nav.memory',
    to: '/memories',
    match: ['/memories'],
    group: 'main',
    icon: <PsychologyRoundedIcon />,
  },
  {
    key: 'files',
    labelKey: 'nav.files',
    to: '/files',
    match: ['/files', '/document'],
    group: 'main',
    icon: <FolderRoundedIcon />,
  },
  {
    key: 'settings',
    labelKey: 'nav.settings',
    to: '/user-setting/model',
    match: ['/user-setting'],
    group: 'bottom',
    icon: <SettingsRoundedIcon />,
  },
  {
    key: 'admin',
    labelKey: 'nav.admin',
    to: '/admin/users',
    match: ['/admin'],
    group: 'bottom',
    icon: <AdminPanelSettingsRoundedIcon />,
  },
]

// Prefiks pasuje, gdy pathname jest równy prefiksowi albo zaczyna się od prefiks + '/'.
// Wyjątek: '/' pasuje wyłącznie dokładnie (inaczej byłby aktywny wszędzie).
export function isNavItemActive(item: NavItem, pathname: string): boolean {
  return item.match.some((prefix) =>
    prefix === '/' ? pathname === '/' : pathname === prefix || pathname.startsWith(`${prefix}/`),
  )
}

export function activeNavItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => isNavItemActive(item, pathname))
}

// Agent/pamięć zależne od flag funkcji, administracja od uprawnień.
export function visibleNavItems(opts: { isSuperuser: boolean; flags: FeatureFlags }): NavItem[] {
  const { isSuperuser, flags } = opts
  return NAV_ITEMS.filter((item) => {
    if (item.key === 'agent') return flags.agent
    if (item.key === 'memory') return flags.memory
    if (item.key === 'admin') return isSuperuser
    return true
  })
}
