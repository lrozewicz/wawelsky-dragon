import type { JSX } from 'react'
import { createFileRoute } from '@tanstack/react-router'

import { ConfigurationTab } from '../../../features/datasets/config/ConfigurationTab'
import { DatasetLayout } from '../../../features/datasets/detail/DatasetLayout'
import { datasetQueryOptions } from '../../../features/datasets/queries'

// Loader rozgrzewa cache szczegółu i oddaje go zakładce; błąd łapie `errorComponent` layoutu.
// T10 (QA-UI #3): formularz inicjalizuje stan przy montowaniu z danych loadera, więc odświeżenie
// musi się dokonać PRZED pierwszym renderem trasy. Dwa elementy:
// 1. `fetchQuery` (a nie `ensureQueryData`) — w TanStack Query 5.103 `ensureQueryData` oddaje
//    cache natychmiast, a nieświeży stan dopiero `prefetchQuery` w tle; `fetchQuery` czeka
//    na GET i dopiero potem oddaje dane.
// 2. `staleReloadMode: 'blocking'` — domyślny tryb routera (`'background'`) renderuje trasę
//    od razu ze starymi danymi dopasowania i dopiero potem odświeża w tle; formularz startuje
//    wówczas ze stanu sprzed zapisu (QA-UI #3) zamiast z chwilą oczekiwania na świeże dane.
export const Route = createFileRoute('/_app/dataset/configuration/$id')({
  loader: {
    handler: ({ context, params }) =>
      context.queryClient.fetchQuery(datasetQueryOptions(params.id)),
    staleReloadMode: 'blocking',
  },
  component: DatasetConfigurationRoute,
})

function DatasetConfigurationRoute(): JSX.Element {
  const { id } = Route.useParams()
  const dataset = Route.useLoaderData()

  return (
    <DatasetLayout datasetId={id} activeTab="configuration">
      <ConfigurationTab dataset={dataset} />
    </DatasetLayout>
  )
}
