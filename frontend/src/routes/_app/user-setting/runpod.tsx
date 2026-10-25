import { Suspense, lazy } from 'react'
import type { JSX } from 'react'
import { createFileRoute } from '@tanstack/react-router'

import { SettingsLayout } from '../../../features/settings/SettingsLayout'

// Strona ładowana leniwie (wzór: `routes/_app/user-setting/api.tsx`).
const RunpodPage = lazy(async () => {
  const module = await import('../../../features/runpod/RunpodPage')
  return { default: module.RunpodPage }
})

export const Route = createFileRoute('/_app/user-setting/runpod')({
  component: UserSettingRunpodRoute,
})

function UserSettingRunpodRoute(): JSX.Element {
  return (
    <SettingsLayout active="runpod">
      <Suspense fallback={null}>
        <RunpodPage />
      </Suspense>
    </SettingsLayout>
  )
}
