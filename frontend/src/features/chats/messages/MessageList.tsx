/**
 * Lista wiadomości czatu (kontrakt WP E3-5b §T5b): historia i bieżąca wymiana z `ChatMessage[]`,
 * ze stanem pustym, auto-scrollem na dół podczas dopisywania odpowiedzi i przyciskiem powrotu
 * na dół, gdy użytkownik przewinął w górę. Akcje i feedback deleguje do `onFeedback`,
 * a powtórzenie odpowiedzi — do `onRegenerate` (DEC-079: nowe pytanie do tej samej sesji).
 */

import { useEffect, useRef, useState } from 'react'
import type { JSX, UIEvent } from 'react'
import KeyboardDoubleArrowDownIcon from '@mui/icons-material/KeyboardDoubleArrowDown'
import Box from '@mui/material/Box'
import Fab from '@mui/material/Fab'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import type { ChatMessage } from '../sessions/chatMessages'

import { AssistantMessage } from './AssistantMessage'
import { UserMessage } from './UserMessage'

export type MessageListProps = {
  messages: ChatMessage[]
  streaming: boolean
  onOpenDocument: (docId: string, docName: string) => void
  onFeedback: (message: ChatMessage, thumbup: boolean, feedback: string | null) => void
  onRegenerate: () => void
}

/** Odległość od dołu (px), poniżej której użytkownik uchodzi za „przy dole” (kontrakt §T5b). */
const BOTTOM_THRESHOLD = 80

export function MessageList(props: MessageListProps): JSX.Element {
  const { messages, streaming, onOpenDocument, onFeedback, onRegenerate } = props
  const { t } = useTranslation()

  const containerRef = useRef<HTMLDivElement | null>(null)
  const [atBottom, setAtBottom] = useState(true)

  const last = messages.at(-1)
  const lastKey = last?.key
  const lastContent = last?.content
  const lastStatus = last?.status

  // Auto-scroll przy każdej zmianie ostatniej wiadomości, ale tylko gdy użytkownik jest przy dole.
  useEffect(() => {
    if (!atBottom) return
    const container = containerRef.current
    if (container === null) return
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
  }, [atBottom, messages.length, lastKey, lastContent, lastStatus])

  // Gdy użytkownik jest przy dole, zmiana WYSOKOŚCI kontenera (autozmiar pola pytania po
  // wysłaniu wielowierszowego tekstu, zwinięcie panelu rozmów) ma utrzymać dolną krawędź —
  // bez tego ostatnia odpowiedź zostaje przycięta przez klip listy (SC-E5-H8d-06).
  useEffect(() => {
    const container = containerRef.current
    if (container === null) return
    const observer = new ResizeObserver(() => {
      if (atBottom) container.scrollTo({ top: container.scrollHeight })
    })
    observer.observe(container)
    return () => observer.disconnect()
  }, [atBottom])

  // „Wygeneruj ponownie” tylko przy ostatniej wiadomości asystenta, już nie w trakcie streamu.
  const lastAssistant = messages.filter((message) => message.role === 'assistant').at(-1)
  const regenerateKey =
    streaming || lastAssistant === undefined || lastAssistant.status === 'streaming'
      ? null
      : lastAssistant.key

  function handleScroll(event: UIEvent<HTMLDivElement>): void {
    const container = event.currentTarget
    setAtBottom(
      container.scrollHeight - container.scrollTop - container.clientHeight <= BOTTOM_THRESHOLD,
    )
  }

  function scrollToBottom(): void {
    const container = containerRef.current
    if (container === null) return
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
    setAtBottom(true)
  }

  return (
    <Box sx={{ position: 'relative', height: '100%', minHeight: 0 }}>
      <Box
        ref={containerRef}
        data-testid="message-list"
        onScroll={handleScroll}
        sx={{ height: '100%', overflowY: 'auto' }}
      >
        <Stack spacing={2} sx={{ p: 2 }}>
          {messages.map((message) =>
            message.role === 'user' ? (
              <UserMessage key={message.key} message={message} />
            ) : (
              <AssistantMessage
                key={message.key}
                message={message}
                onOpenDocument={onOpenDocument}
                onFeedback={onFeedback}
                onRegenerate={message.key === regenerateKey ? onRegenerate : undefined}
              />
            ),
          )}
        </Stack>
      </Box>

      {atBottom ? null : (
        <Fab
          size="small"
          aria-label={t('chat.msg.scrollToBottom')}
          onClick={scrollToBottom}
          sx={{ position: 'absolute', right: 16, bottom: 16 }}
        >
          <KeyboardDoubleArrowDownIcon />
        </Fab>
      )}
    </Box>
  )
}
