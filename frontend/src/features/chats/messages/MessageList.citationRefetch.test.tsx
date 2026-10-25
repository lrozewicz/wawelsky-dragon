// Refetch sesji po `done` (useChatStream) zamienia parę „live” na parę z historii —
// komponenty wiadomości nie mogą się przy tym remontować, bo otwarty modal cytowania
// zamyka się zaraz po kliknięciu tuż po końcu odpowiedzi (SC-V13-z-01).
import { useState } from 'react'
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { initialStreamState } from '../../chat-stream/reducer'
import type { Citation } from '../../chat-stream/reducer'
import { historyToMessages, liveToMessages } from '../sessions/chatMessages'
import type { ChatMessage } from '../sessions/chatMessages'
import type { Session } from '../sessions/sessionQueries'

import { MessageList } from './MessageList'

afterEach(cleanup)

/** Stub `scrollTo`: jsdom nie implementuje tej metody (auto-scroll kontenera, §T5b). */
const scrollTo = vi.fn()
beforeEach(() => {
  scrollTo.mockClear()
  Object.defineProperty(Element.prototype, 'scrollTo', {
    value: scrollTo,
    configurable: true,
    writable: true,
  })
})

/** Napisy z `locales/pl/*.json` — test chodzi na interfejsie polskim (domyślnym w `renderWithProviders`). */
const CHIP_LABEL = 'Cytowanie 1'
const DOC_NAME = 'Smok.pdf'
const CONTENT = 'Smok wawelski mieszkał pod Wawelem.'

/** Rodzic stanowy (jak `ChatWorkspacePage`): zamiana pary live na parę z historii w tym samym drzewie. */
function SwapMessages({ first, second }: { first: ChatMessage[]; second: ChatMessage[] }) {
  const [messages, setMessages] = useState(first)
  return (
    <>
      <button onClick={() => setMessages(second)}>refetch sesji</button>
      <MessageList
        messages={messages}
        streaming={false}
        onOpenDocument={vi.fn()}
        onFeedback={vi.fn()}
        onRegenerate={vi.fn()}
      />
    </>
  )
}

describe('modal cytowania przeżywa refetch sesji (SC-V13-z-01)', () => {
  it('nie remontuje wiadomości przy zamianie pary live na parę z historii', async () => {
    const citation: Citation = {
      chunkId: 'c1',
      docId: 'doc-1',
      docName: DOC_NAME,
      content: CONTENT,
      similarity: 0.87,
    }
    // Para live po `done` (useChatStream): treść i cytowania z reduktora, id pary z ramki.
    const live = liveToMessages(
      'Kim jest smok?',
      {
        ...initialStreamState,
        status: 'done',
        answer: 'Smok mieszka na Wawelu [ID:0].',
        citations: [citation],
        messageId: 'm1',
      },
      'done',
    )
    // Ta sama para w historii sesji: user i assistant dzielą `id` (K4 §3.3) — klucze
    // `user-m1`/`assistant-m1`, treść i cytowania z `reference` (identyczne jak live).
    const session = {
      id: 's1',
      name: 'Alfa',
      messages: [
        { role: 'user', content: 'Kim jest smok?', id: 'm1' },
        {
          role: 'assistant',
          content: 'Smok mieszka na Wawelu [ID:0].',
          id: 'm1',
          created_at: 1735689600,
        },
      ],
      reference: [
        {
          chunks: [
            {
              id: 'c1',
              content: CONTENT,
              document_id: 'doc-1',
              document_name: DOC_NAME,
              similarity: 0.87,
            },
          ],
          total: 1,
        },
      ],
    } as Session
    const history = historyToMessages(session)
    expect(history.map((message) => message.key)).toEqual(['user-m1', 'assistant-m1'])

    await renderWithProviders(<SwapMessages first={live} second={history} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: CHIP_LABEL }))
    expect(screen.getByRole('dialog', { name: DOC_NAME })).toBeInTheDocument()
    // Chip za otwartym dialogiem jest `aria-hidden` — rolę bierzemy z `hidden: true` (stan `open`
    // czytamy z `aria-expanded` chipa, nie z DOM modala, którego animacja wyjścia MUI opóźnia).
    const openChip = () => screen.getByRole('button', { name: CHIP_LABEL, hidden: true })
    expect(openChip()).toHaveAttribute('aria-expanded', 'true')

    // Refetch po `done` podmienia wiadomości na historię (ta sama treść i cytowania).
    // Przycisk też jest za dialogiem — stąd `hidden: true`.
    await user.click(screen.getByRole('button', { name: 'refetch sesji', hidden: true }))

    // Stan `open` chipa ma przeżyć zamianę — remont komponentu (różne klucze) go zeruje
    // i modal cytowania zamyka się zaraz po kliknięciu (USTERKA SC-V13-z-01).
    expect(openChip()).toHaveAttribute('aria-expanded', 'true')
    await waitFor(() => expect(screen.getByRole('dialog', { name: DOC_NAME })).toBeInTheDocument())
  })
})
