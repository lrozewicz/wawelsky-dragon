import type { JSX } from 'react'
import { createFileRoute } from '@tanstack/react-router'

import { DatasetLayout } from '../../../features/datasets/detail/DatasetLayout'
import { DatasetFilesTab } from '../../../features/datasets/files/DatasetFilesTab'
import { datasetQueryOptions } from '../../../features/datasets/queries'

// Loader rozgrzewa cache szczegółu; błąd wczytania łapie `errorComponent` layoutu `/_app/dataset`.
export const Route = createFileRoute('/_app/dataset/files/$id')({
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(datasetQueryOptions(params.id)),
  component: DatasetFilesRoute,
})

function DatasetFilesRoute(): JSX.Element {
  const { id } = Route.useParams()

  return (
    <DatasetLayout datasetId={id} activeTab="files">
      <DatasetFilesTab datasetId={id} />
    </DatasetLayout>
  )
}
