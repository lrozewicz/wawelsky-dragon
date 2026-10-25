import { createFileRoute } from '@tanstack/react-router'
import { zodValidator } from '@tanstack/zod-adapter'
import { z } from 'zod'

import { DatasetsPage } from '../../../features/datasets/DatasetsPage'

// `?isCreate=true` — link z Home otwiera dialog tworzenia datasetu (kontrakt WP E3-3a §T2).
export const datasetsSearchSchema = z.object({
  isCreate: z.boolean().optional(),
})

export const Route = createFileRoute('/_app/datasets/')({
  validateSearch: zodValidator(datasetsSearchSchema),
  component: DatasetsPage,
})
