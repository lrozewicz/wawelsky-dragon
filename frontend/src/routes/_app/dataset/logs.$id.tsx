import { Suspense, lazy } from 'react'
import type { JSX } from 'react'
import Skeleton from '@mui/material/Skeleton'
import { createFileRoute } from '@tanstack/react-router'

import { DatasetLayout } from '../../../features/datasets/detail/DatasetLayout'
import { datasetQueryOptions } from '../../../features/datasets/queries'

// Siatka zadań ciągnie `@mui/x-data-grid` — ładujemy ją leniwie, by nie obciążać startowego chunku
// (kontrakt WP E3-3a §T5: początkowy JS gzip ≤ 350 kB).
const LogsTab = lazy(async () => {
  const module = await import('../../../features/datasets/logs/LogsTab')
  return { default: module.LogsTab }
})

// Loader rozgrzewa cache szczegółu; błąd wczytania łapie `errorComponent` layoutu `/_app/dataset`.
export const Route = createFileRoute('/_app/dataset/logs/$id')({
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(datasetQueryOptions(params.id)),
  component: DatasetLogsRoute,
})

function DatasetLogsRoute(): JSX.Element {
  const { id } = Route.useParams()

  return (
    <DatasetLayout datasetId={id} activeTab="logs">
      <Suspense fallback={<Skeleton variant="rounded" height={420} />}>
        <LogsTab datasetId={id} />
      </Suspense>
    </DatasetLayout>
  )
}
