import { Suspense, lazy } from 'react'
import type { JSX } from 'react'
import { createFileRoute } from '@tanstack/react-router'

import { SettingsLayout } from '../../../features/settings/SettingsLayout'
import { GridSkeleton } from '../../../features/settings/api/GridSkeleton'

// Strona ładowana leniwie (wzór: `routes/_app/admin/users.tsx`).
const ApiKeysPage = lazy(async () => {
  const module = await import('../../../features/settings/api/ApiKeysPage')
  return { default: module.ApiKeysPage }
})

export const Route = createFileRoute('/_app/user-setting/api')({
  component: UserSettingApiRoute,
})

function UserSettingApiRoute(): JSX.Element {
  return (
    <SettingsLayout active="api">
      {/* Szkielet wierszy zamiast gołego prostokąta (QA V12-z-2b MINOR-2) — ten fallback widzi
          użytkownik pierwszy, zanim dojdzie czekanie na chunk `KeysGrid` w `ApiKeysPage`. */}
      <Suspense fallback={<GridSkeleton />}>
        <ApiKeysPage />
      </Suspense>
    </SettingsLayout>
  )
}
