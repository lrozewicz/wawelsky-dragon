import { createFileRoute } from '@tanstack/react-router'

import { SearchPage } from '../../../features/searches/SearchPage'

export const Route = createFileRoute('/_app/search/$id')({
  component: SearchRoute,
})

function SearchRoute() {
  const { id } = Route.useParams()

  return <SearchPage searchId={id} />
}
