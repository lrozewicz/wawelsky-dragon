/**
 * Taby dostawców GPU w Ustawienia → GPU. Nowy dostawca to wpis w `GPU_TABS` i trasa w
 * `routes/_app/user-setting/gpu/`.
 */

import type { JSX, ReactNode } from 'react'
import { Link, useRouterState } from '@tanstack/react-router'
import Stack from '@mui/material/Stack'
import Tab from '@mui/material/Tab'
import type { TabProps } from '@mui/material/Tab'
import Tabs from '@mui/material/Tabs'
import { useTranslation } from 'react-i18next'

export const GPU_TABS = [
  { key: 'runpod', to: '/user-setting/gpu/runpod' },
  { key: 'local', to: '/user-setting/gpu/local' },
] as const

export function GpuTabs(props: { children: ReactNode }): JSX.Element {
  const { t } = useTranslation()
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const active = GPU_TABS.find((tab) => pathname.startsWith(tab.to))?.key ?? 'runpod'

  return (
    <Stack spacing={2} sx={{ flex: 1 }}>
      <Tabs value={active} aria-label={t('settings.tabs.gpu')}>
        {GPU_TABS.map((tab) => (
          <Tab
            key={tab.key}
            value={tab.key}
            label={t(`runpod.tabs.${tab.key}`)}
            data-testid={`gpu-tab-${tab.key}`}
            {...({ component: Link, to: tab.to } as TabProps)}
          />
        ))}
      </Tabs>
      {props.children}
    </Stack>
  )
}
