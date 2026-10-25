/**
 * Układ sekcji administracyjnej (kontrakt WP E3-6c2 §4): nagłówek „Administracja” i zakładki
 * Użytkownicy · Dostęp do asystentów · Status systemu (+ Integracje, gdy `showIntegrations`).
 * Zakładki są linkami tras `/_app/admin/*` — wzór: `DatasetTabs` w szczegółach datasetu
 * (rzutowanie propsów `TabProps`); poniżej progu `md` zawijają się do kolejnych rzędów,
 * by żadna nie była przycięta ani zasłonięta (R-UI-02).
 */

import { Suspense } from 'react'
import type { JSX, ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import Container from '@mui/material/Container'
import Skeleton from '@mui/material/Skeleton'
import Stack from '@mui/material/Stack'
import Tab from '@mui/material/Tab'
import type { TabProps } from '@mui/material/Tab'
import Tabs from '@mui/material/Tabs'
import Typography from '@mui/material/Typography'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useTranslation } from 'react-i18next'

export type AdminTabKey = 'users' | 'access' | 'status' | 'integrations'

/** Kolejność zakładek z kontraktu §4; `integrations` pokazujemy tylko na życzenie (§4, slot E4-3c). */
export const ADMIN_TABS: readonly AdminTabKey[] = ['users', 'access', 'status', 'integrations']

/** Adresy tras zakładek — id tras z `routes/_app/admin/*.tsx`. */
const TAB_PATHS = {
  users: '/admin/users',
  access: '/admin/access',
  status: '/admin/status',
  integrations: '/admin/integrations',
} as const

/**
 * MUI normalizuje props `component` do generycznego `LinkComponent`, przez co typy celu linku
 * degenerują się do wariantu funkcyjnego — rzutujemy więc same propsy linku-routera.
 */
function adminTabLinkProps(key: AdminTabKey): TabProps {
  return {
    component: Link,
    to: TAB_PATHS[key],
  } as TabProps
}

export type AdminLayoutProps = {
  active: AdminTabKey
  children: ReactNode
  showIntegrations?: boolean
}

export function AdminLayout(props: AdminLayoutProps): JSX.Element {
  const { active, children, showIntegrations = false } = props
  const { t } = useTranslation()
  // jsdom nie zna `matchMedia` — MUI zwraca wtedy `defaultMatches` (false), czyli wariant `standard`.
  const belowMd = useMediaQuery((theme) => theme.breakpoints.down('md'))
  const tabs = showIntegrations ? ADMIN_TABS : ADMIN_TABS.filter((key) => key !== 'integrations')

  return (
    <Container maxWidth="lg" sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
      <Stack spacing={2} sx={{ flex: 1, my: 2 }}>
        <Typography variant="h4" component="h1">
          {t('admin.title')}
        </Typography>
        <Tabs
          value={active}
          variant={belowMd ? 'scrollable' : 'standard'}
          // U6 (s14) → zmiana (SC-E5-H8z-03): poniżej `md` zakładki zawijają do kolejnych
          // rzędów, więc żadna nie jest przycięta i wszystkie są osiągalne bez przewijania —
          // `scrollButtons` wyłączone, bo widoczne (albo zarezerwowane) przyciski dawały ~40 px
          // pustki przed pierwszą zakładką. `allowScrollButtonsMobile` zbędne (nic nie rezerwuje).
          scrollButtons={belowMd ? false : 'auto'}
          aria-label={t('admin.title')}
          sx={{
            borderBottom: 1,
            borderColor: 'divider',
            ...(belowMd
              ? {
                  // Zawijanie zamiast przewijania w poziomie (U3): żadna zakładka nie wychodzi
                  // poza ekran. Mniejszy poziomy padding, by dwa rzędy mieściły się na 390 px.
                  '& .MuiTabs-list': { flexWrap: 'wrap' },
                  '& .MuiTab-root': { px: 1 },
                  // Wskaźnik MUI liczony jest dla jednej linii — przy zawijaniu trafiłby na zły
                  // rząd; aktywną zakładkę wyróżnia tło (czytelne też bez linii pod spodem).
                  '& .MuiTabs-indicator': { display: 'none' },
                  '& .MuiTab-root[aria-selected="true"]': { bgcolor: 'action.selected' },
                }
              : {}),
          }}
        >
          {tabs.map((key) => (
            <Tab
              key={key}
              value={key}
              label={t(`admin.tabs.${key}`)}
              data-testid={`admin-tab-${key}`}
              {...adminTabLinkProps(key)}
            />
          ))}
        </Tabs>
        {/* Szkielet zamiast pustego ekranu podczas ładowania strony zakładki (U5; SC-E5-H9-07
            k. 4) — wysokość jak siatka, by układ nie skakał po dołączeniu treści. */}
        <Stack sx={{ flex: 1 }}>
          <Suspense fallback={<Skeleton variant="rounded" height={420} />}>{children}</Suspense>
        </Stack>
      </Stack>
    </Container>
  )
}
