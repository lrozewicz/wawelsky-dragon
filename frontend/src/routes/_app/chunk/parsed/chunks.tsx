import { createFileRoute } from '@tanstack/react-router'
import { zodValidator } from '@tanstack/zod-adapter'
import { z } from 'zod'

import { ChunksPage } from '../../../../features/datasets/chunks/ChunksPage'

/**
 * Strona chunków dokumentu (08 §7.4/§7.5, kontrakt WP E3-4a §Trasa): URL
 * `/chunk/parsed/chunks?id=<dataset>&doc_id=<dokument>` — podgląd dokumentu i lista chunków.
 * Trasa jest dzieckiem layoutu `/_app` (guard `requireSession`), więc dziedziczy powłokę
 * i ochronę sesji.
 */
export const chunksSearchSchema = z.object({
  id: z.string(),
  doc_id: z.string(),
})

export const Route = createFileRoute('/_app/chunk/parsed/chunks')({
  validateSearch: zodValidator(chunksSearchSchema),
  component: ChunksRoute,
})

function ChunksRoute() {
  const { id, doc_id } = Route.useSearch()

  return <ChunksPage datasetId={id} docId={doc_id} />
}
