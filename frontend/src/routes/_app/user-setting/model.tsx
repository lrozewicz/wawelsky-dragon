import { Suspense, lazy } from 'react'
import type { JSX } from 'react'
import Skeleton from '@mui/material/Skeleton'
import { createFileRoute } from '@tanstack/react-router'

import { SettingsLayout } from '../../../features/settings/SettingsLayout'

// Strona ciągnie siatkę modeli — ładujemy ją leniwie (wzór: `routes/_app/admin/users.tsx`).
const ModelsPage = lazy(async () => {
  const module = await import('../../../features/settings/model/ModelsPage')
  return { default: module.ModelsPage }
})

export const Route = createFileRoute('/_app/user-setting/model')({
  component: UserSettingModelRoute,
})

function UserSettingModelRoute(): JSX.Element {
  return (
    <SettingsLayout active="model">
      <Suspense fallback={<Skeleton variant="rounded" height={420} />}>
        <ModelsPage />
      </Suspense>
    </SettingsLayout>
  )
}
