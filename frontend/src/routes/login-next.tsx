import { createFileRoute, redirect } from '@tanstack/react-router'

// Adres zgodnościowy: `/login-next` prowadzi do właściwej trasy `/login` (CONTRACT §Trasy).
export const Route = createFileRoute('/login-next')({
  beforeLoad: () => {
    throw redirect({ to: '/login' })
  },
})
