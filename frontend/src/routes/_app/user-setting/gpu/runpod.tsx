import { Suspense, lazy } from 'react'
import type { JSX } from 'react'
import { createFileRoute } from '@tanstack/react-router'

const RunpodPage = lazy(async () => {
  const module = await import('../../../../features/runpod/RunpodPage')
  return { default: module.RunpodPage }
})

export const Route = createFileRoute('/_app/user-setting/gpu/runpod')({
  component: GpuRunpodRoute,
})

function GpuRunpodRoute(): JSX.Element {
  return (
    <Suspense fallback={null}>
      <RunpodPage />
    </Suspense>
  )
}
