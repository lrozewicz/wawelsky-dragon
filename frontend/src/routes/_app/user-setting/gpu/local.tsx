import { Suspense, lazy } from 'react'
import type { JSX } from 'react'
import { createFileRoute } from '@tanstack/react-router'

const LocalGpuPage = lazy(async () => {
  const module = await import('../../../../features/runpod/LocalGpuPage')
  return { default: module.LocalGpuPage }
})

export const Route = createFileRoute('/_app/user-setting/gpu/local')({
  component: GpuLocalRoute,
})

function GpuLocalRoute(): JSX.Element {
  return (
    <Suspense fallback={null}>
      <LocalGpuPage />
    </Suspense>
  )
}
