import type { JSX } from 'react'
import { Outlet, createFileRoute } from '@tanstack/react-router'

import { GpuTabs } from '../../../features/runpod/GpuTabs'
import { SettingsLayout } from '../../../features/settings/SettingsLayout'

export const Route = createFileRoute('/_app/user-setting/gpu')({
  component: UserSettingGpuRoute,
})

function UserSettingGpuRoute(): JSX.Element {
  return (
    <SettingsLayout active="gpu">
      <GpuTabs>
        <Outlet />
      </GpuTabs>
    </SettingsLayout>
  )
}
