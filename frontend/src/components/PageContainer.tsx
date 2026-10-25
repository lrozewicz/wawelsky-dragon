// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/crud-dashboard/components/PageContainer.tsx (MIT). Zmiany: `Link` z `react-router` → `@tanstack/react-router` (rzutowanie typu `to`), `aria-label` breadcrumbs z i18n (`nav.breadcrumb`), import typu `ContainerProps` przez `import type`, formatowanie Prettier, `responsiveHeader` (E7-2 T17) — na `xs` akcje schodzą pod tytuł, zanim tytuł lub przycisk złamie się na dwie linie (opt-in, by nie zmieniać innych stron).
import * as React from 'react'
import { useTranslation } from 'react-i18next'
import { styled } from '@mui/material/styles'
import Box from '@mui/material/Box'
import Breadcrumbs, { breadcrumbsClasses } from '@mui/material/Breadcrumbs'
import Container from '@mui/material/Container'
import type { ContainerProps } from '@mui/material/Container'
import MuiLink from '@mui/material/Link'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import NavigateNextRoundedIcon from '@mui/icons-material/NavigateNextRounded'
import { Link } from '@tanstack/react-router'
import type { LinkProps } from '@tanstack/react-router'

const PageContentHeader = styled('div', {
  shouldForwardProp: (prop) => prop !== 'responsive',
})<{ responsive?: boolean }>(({ theme, responsive }) => ({
  display: 'flex',
  flexDirection: 'row',
  justifyContent: 'space-between',
  gap: theme.spacing(2),
  // E7-2 T17: opt-in dla nagłówków, których tytuł i akcje nie mieszczą się obok siebie na wąskim
  // ekranie — na `xs` akcje schodzą pod tytuł (każdy element w jednej linii), od `sm` jak dotąd.
  ...(responsive ? { [theme.breakpoints.down('sm')]: { flexDirection: 'column' } } : {}),
}))

const PageHeaderBreadcrumbs = styled(Breadcrumbs)(({ theme }) => ({
  margin: theme.spacing(1, 0),
  [`& .${breadcrumbsClasses.separator}`]: {
    color: (theme.vars || theme).palette.action.disabled,
    margin: 1,
  },
  [`& .${breadcrumbsClasses.ol}`]: {
    alignItems: 'center',
  },
}))

const PageHeaderToolbar = styled('div')(({ theme }) => ({
  display: 'flex',
  flexDirection: 'row',
  gap: theme.spacing(1),
  // Ensure the toolbar is always on the right side, even after wrapping
  marginLeft: 'auto',
}))

export interface Breadcrumb {
  title: string
  path?: string
}
export interface PageContainerProps extends ContainerProps {
  children?: React.ReactNode
  title?: string
  breadcrumbs?: Breadcrumb[]
  actions?: React.ReactNode
  /** E7-2 T17: na `xs` akcje pod tytułem (od `sm` obok siebie) — dla nagłówków z wieloma przyciskami. */
  responsiveHeader?: boolean
}

export default function PageContainer(props: PageContainerProps) {
  const { t } = useTranslation()
  const { children, breadcrumbs, title, actions = null, responsiveHeader = false } = props

  return (
    <Container sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
      <Stack sx={{ flex: 1, my: 2 }} spacing={2}>
        <Stack>
          <PageHeaderBreadcrumbs
            aria-label={t('nav.breadcrumb')}
            separator={<NavigateNextRoundedIcon fontSize="small" />}
          >
            {breadcrumbs
              ? breadcrumbs.map((breadcrumb, index) => {
                  return breadcrumb.path ? (
                    // trasy dochodzą w E3-2…E3-6, typ `to` rozluźniony w jednym miejscu
                    <MuiLink
                      key={index}
                      component={Link}
                      underline="hover"
                      color="inherit"
                      to={breadcrumb.path as LinkProps['to']}
                    >
                      {breadcrumb.title}
                    </MuiLink>
                  ) : (
                    <Typography key={index} sx={{ color: 'text.primary', fontWeight: 600 }}>
                      {breadcrumb.title}
                    </Typography>
                  )
                })
              : null}
          </PageHeaderBreadcrumbs>
          <PageContentHeader responsive={responsiveHeader}>
            {title ? <Typography variant="h4">{title}</Typography> : null}
            <PageHeaderToolbar>{actions}</PageHeaderToolbar>
          </PageContentHeader>
        </Stack>
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>{children}</Box>
      </Stack>
    </Container>
  )
}
