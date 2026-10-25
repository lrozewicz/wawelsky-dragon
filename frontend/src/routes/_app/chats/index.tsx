import { createFileRoute } from '@tanstack/react-router'
import { zodValidator } from '@tanstack/zod-adapter'
import { z } from 'zod'

import { ChatsPage } from '../../../features/chats/ChatsPage'

// `?isCreate=true` — link z Home otwiera okno tworzenia czatu (kontrakt WP E3-5a §7).
export const chatsSearchSchema = z.object({
  isCreate: z.boolean().optional(),
})

export const Route = createFileRoute('/_app/chats/')({
  validateSearch: zodValidator(chatsSearchSchema),
  component: ChatsPage,
})
