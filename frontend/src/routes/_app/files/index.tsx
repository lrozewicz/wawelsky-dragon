import { createFileRoute } from '@tanstack/react-router'
import { zodValidator } from '@tanstack/zod-adapter'
import { z } from 'zod'

import { FilesPage } from '../../../features/files/FilesPage'

// `?folder=<id>` wybiera folder w menedżerze plików (kontrakt WP E4-5c §7).
export const filesSearchSchema = z.object({
  folder: z.string().optional(),
})

export const Route = createFileRoute('/_app/files/')({
  validateSearch: zodValidator(filesSearchSchema),
  component: FilesPage,
})
