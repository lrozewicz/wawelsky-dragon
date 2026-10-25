import type { JSX } from 'react'
import { createFileRoute } from '@tanstack/react-router'

import { DatasetLayout } from '../../../features/datasets/detail/DatasetLayout'
import { datasetQueryOptions } from '../../../features/datasets/queries'
import { RetrievalTab } from '../../../features/datasets/retrieval/RetrievalTab'

// Loader rozgrzewa cache szczegółu; błąd wczytania łapie `errorComponent` layoutu `/_app/dataset`.
export const Route = createFileRoute('/_app/dataset/retrieval/$id')({
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(datasetQueryOptions(params.id)),
  component: DatasetRetrievalRoute,
})

function DatasetRetrievalRoute(): JSX.Element {
  const { id } = Route.useParams()

  return (
    <DatasetLayout datasetId={id} activeTab="retrieval">
      <RetrievalTab datasetId={id} />
    </DatasetLayout>
  )
}
