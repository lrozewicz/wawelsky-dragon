import { createFileRoute, redirect } from '@tanstack/react-router'

// `/user-setting/gpu` to tylko wejście do sekcji: pierwszy dostawca.
export const Route = createFileRoute('/_app/user-setting/gpu/')({
  beforeLoad: () => {
    throw redirect({ to: '/user-setting/gpu/runpod' })
  },
})
