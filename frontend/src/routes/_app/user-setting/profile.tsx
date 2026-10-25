import { Suspense, lazy } from 'react'
import type { JSX } from 'react'
import Skeleton from '@mui/material/Skeleton'
import { createFileRoute } from '@tanstack/react-router'

import { SettingsLayout } from '../../../features/settings/SettingsLayout'

// Strona ładowana leniwie (wzór: `routes/_app/admin/users.tsx`).
const ProfilePage = lazy(async () => {
  const module = await import('../../../features/settings/profile/ProfilePage')
  return { default: module.ProfilePage }
})

export const Route = createFileRoute('/_app/user-setting/profile')({
  component: UserSettingProfileRoute,
})

function UserSettingProfileRoute(): JSX.Element {
  return (
    <SettingsLayout active="profile">
      <Suspense fallback={<Skeleton variant="rounded" height={420} />}>
        <ProfilePage />
      </Suspense>
    </SettingsLayout>
  )
}
