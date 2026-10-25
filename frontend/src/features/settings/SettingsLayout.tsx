/**
 * Układ sekcji Ustawień (kontrakt WP E3-6c1 §4): nagłówek „Ustawienia” i zakładki-linki
 * Dostawcy modeli · Profil · Klucze API · RunPod. Wzór: `features/admin/AdminLayout.tsx`.
 */

import type { JSX, ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import Container from '@mui/material/Container'
import Stack from '@mui/material/Stack'
import Tab from '@mui/material/Tab'
import type { TabProps } from '@mui/material/Tab'
import Tabs from '@mui/material/Tabs'
import Typography from '@mui/material/Typography'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useTranslation } from 'react-i18next'

export type SettingsTabKey = 'model' | 'profile' | 'api' | 'runpod'

/** Kolejność zakładek z kontraktu §4. */
export const SETTINGS_TABS: readonly SettingsTabKey[] = ['model', 'profile', 'api', 'runpod']

/** Adresy tras zakładek — id tras z `routes/_app/user-setting/*.tsx`. */
const TAB_PATHS = {
  model: '/user-setting/model',
  profile: '/user-setting/profile',
  api: '/user-setting/api',
  runpod: '/user-setting/runpod',
} as const

/**
 * MUI normalizuje props `component` do generycznego `LinkComponent`, przez co typy celu linku
 * degenerują się do wariantu funkcyjnego — rzutujemy więc same propsy linku-routera.
 */
function settingsTabLinkProps(key: SettingsTabKey): TabProps {
  return {
    component: Link,
    to: TAB_PATHS[key],
  } as TabProps
}

export type SettingsLayoutProps = {
  active: SettingsTabKey
  children: ReactNode
}

export function SettingsLayout(props: SettingsLayoutProps): JSX.Element {
  const { active, children } = props
  const { t } = useTranslation()
  // jsdom nie zna `matchMedia` — MUI zwraca wtedy `defaultMatches` (false), czyli wariant `standard`.
  const belowMd = useMediaQuery((theme) => theme.breakpoints.down('md'))

  return (
    <Container maxWidth="lg" sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
      <Stack spacing={2} sx={{ flex: 1, my: 2 }}>
        <Typography variant="h4" component="h1">
          {t('settings.title')}
        </Typography>
        <Tabs
          value={active}
          variant={belowMd ? 'scrollable' : 'standard'}
          aria-label={t('settings.title')}
          sx={{ borderBottom: 1, borderColor: 'divider' }}
        >
          {SETTINGS_TABS.map((key) => (
            <Tab
              key={key}
              value={key}
              label={t(`settings.tabs.${key}`)}
              data-testid={`settings-tab-${key}`}
              {...settingsTabLinkProps(key)}
            />
          ))}
        </Tabs>
        <Stack sx={{ flex: 1 }}>{children}</Stack>
      </Stack>
    </Container>
  )
}
