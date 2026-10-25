import { createFileRoute, redirect } from '@tanstack/react-router'

// `/admin` to tylko wejście do sekcji — kierujemy na pierwszą zakładkę (kontrakt WP E3-6c2 §5).
export const Route = createFileRoute('/_app/admin/')({
  beforeLoad: () => {
    throw redirect({ to: '/admin/users' })
  },
})
