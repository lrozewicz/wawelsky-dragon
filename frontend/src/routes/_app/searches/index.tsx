import { createFileRoute } from '@tanstack/react-router'

import { SearchesPage } from '../../../features/searches/SearchesPage'

export const Route = createFileRoute('/_app/searches/')({
  component: SearchesPage,
})
