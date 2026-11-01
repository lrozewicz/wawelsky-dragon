import { createFileRoute, redirect } from '@tanstack/react-router'

// Dawny adres zakładki RunPod: strona jest teraz w Ustawienia → GPU.
export const Route = createFileRoute('/_app/user-setting/runpod')({
  beforeLoad: () => {
    throw redirect({ to: '/user-setting/gpu/runpod' })
  },
})
