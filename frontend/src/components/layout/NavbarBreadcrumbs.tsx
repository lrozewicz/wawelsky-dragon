// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/dashboard/components/NavbarBreadcrumbs.tsx (MIT). Zmiany: eksport named, prop `pathname`, teksty przez i18n (app.name + etykieta aktywnej pozycji z NAV_ITEMS), styl przeniesiony ze styled() do sx, formatowanie Prettier.
import Typography from '@mui/material/Typography'
import Breadcrumbs, { breadcrumbsClasses } from '@mui/material/Breadcrumbs'
import NavigateNextRoundedIcon from '@mui/icons-material/NavigateNextRounded'
import { useTranslation } from 'react-i18next'

import { activeNavItem } from './navItems'

export function NavbarBreadcrumbs(props: { pathname: string }) {
  const { t } = useTranslation()
  const item = activeNavItem(props.pathname)

  return (
    <Breadcrumbs
      aria-label={t('nav.breadcrumb')}
      separator={<NavigateNextRoundedIcon fontSize="small" />}
      sx={{
        margin: (theme) => theme.spacing(1, 0),
        [`& .${breadcrumbsClasses.separator}`]: {
          color: 'action.disabled',
          margin: 1,
        },
        [`& .${breadcrumbsClasses.ol}`]: {
          alignItems: 'center',
        },
      }}
    >
      <Typography variant="body1">{t('app.name')}</Typography>
      {item ? (
        <Typography variant="body1" sx={{ color: 'text.primary', fontWeight: 600 }}>
          {t(item.labelKey)}
        </Typography>
      ) : null}
    </Breadcrumbs>
  )
}
