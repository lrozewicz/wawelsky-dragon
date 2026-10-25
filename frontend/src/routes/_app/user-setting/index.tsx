import { createFileRoute, redirect } from '@tanstack/react-router'

// `/user-setting` to tylko wejście do sekcji — kierujemy na pierwszą zakładkę (kontrakt §4).
export const Route = createFileRoute('/_app/user-setting/')({
  beforeLoad: () => {
    throw redirect({ to: '/user-setting/model' })
  },
})
