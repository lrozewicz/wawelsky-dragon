// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/dashboard/components/Header.tsx (MIT). Zmiany: eksport named, propsy `pathname` i `onLanguageChange`, okruszki z NavbarBreadcrumbs, po prawej LanguageMenu + ColorModeIconDropdown (bez wyszukiwarki, date pickera i powiadomień), import typu przez `import type`, formatowanie Prettier.
import Stack from '@mui/material/Stack'

import ColorModeIconDropdown from '../../theme/ColorModeIconDropdown'
import type { Language } from '../../i18n'

import { LanguageMenu } from './LanguageMenu'
import { NavbarBreadcrumbs } from './NavbarBreadcrumbs'

export function Header(props: {
  pathname: string
  onLanguageChange: (language: Language) => void
}) {
  const { pathname, onLanguageChange } = props

  return (
    <Stack
      direction="row"
      sx={{
        display: { xs: 'none', md: 'flex' },
        width: '100%',
        alignItems: { xs: 'flex-start', md: 'center' },
        justifyContent: 'space-between',
        maxWidth: { sm: '100%', md: '1700px' },
        pt: 1.5,
      }}
      spacing={2}
    >
      <NavbarBreadcrumbs pathname={pathname} />
      <Stack direction="row" sx={{ gap: 1, alignItems: 'center' }}>
        <LanguageMenu onLanguageChange={onLanguageChange} />
        <ColorModeIconDropdown />
      </Stack>
    </Stack>
  )
}
