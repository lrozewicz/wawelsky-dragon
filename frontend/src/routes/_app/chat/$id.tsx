import { createFileRoute } from '@tanstack/react-router'
import { zodValidator } from '@tanstack/zod-adapter'
import { z } from 'zod'

import { ChatWorkspacePage } from '../../../features/chats/ChatWorkspacePage'

// `?conversationId=<id>` — wybrana sesja czatu; brak = rozmowa tymczasowa (DEC-078).
export const chatSearchSchema = z.object({
  conversationId: z.string().optional(),
})

export const Route = createFileRoute('/_app/chat/$id')({
  validateSearch: zodValidator(chatSearchSchema),
  // Obszar roboczy czatu jest pełnoekranowy — powłoka zwija menu boczne do trybu mini.
  staticData: { fullBleed: true },
  component: ChatWorkspaceRoute,
})

function ChatWorkspaceRoute() {
  const { id } = Route.useParams()
  const { conversationId } = Route.useSearch()
  const navigate = Route.useNavigate()

  return (
    <ChatWorkspacePage
      chatId={id}
      conversationId={conversationId}
      onConversationChange={(sessionId) =>
        // `replace` — wybór rozmowy nie zaśmieca historii przeglądarki (08 §6.2).
        void navigate({ search: { conversationId: sessionId ?? undefined }, replace: true })
      }
    />
  )
}
