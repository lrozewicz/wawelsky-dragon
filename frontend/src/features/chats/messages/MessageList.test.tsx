import { useState } from 'react'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { AssistantMessage } from './AssistantMessage'
import { MessageList } from './MessageList'
import type { MessageListProps } from './MessageList'
import type { ChatMessage } from '../sessions/chatMessages'

afterEach(cleanup)

/** Stub `scrollTo`: jsdom nie implementuje tej metody (kontrakt §T5b — auto-scroll kontenera). */
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
const THINKING = 'Myślenie…'
const REGENERATE = 'Wygeneruj ponownie'
const SCROLL_DOWN = 'Przewiń na dół'
const USER_ROLE = 'Twoja wiadomość'
const ASSISTANT_ROLE = 'Odpowiedź asystenta'

function chatMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    key: 'a1',
    id: 'a1',
    role: 'assistant',
    content: 'Odpowiedź',
    thinking: '',
    citations: [],
    docAggs: [],
    thumbup: null,
    status: 'done',
    error: null,
    ...overrides,
  }
}

async function renderList(messages: ChatMessage[], overrides: Partial<MessageListProps> = {}) {
  const onOpenDocument = vi.fn()
  const onFeedback = vi.fn()
  const onRegenerate = vi.fn()
  await renderWithProviders(
    <MessageList
      messages={messages}
      streaming={false}
      onOpenDocument={onOpenDocument}
      onFeedback={onFeedback}
      onRegenerate={onRegenerate}
      {...overrides}
    />,
  )
  return { onOpenDocument, onFeedback, onRegenerate }
}

describe('MessageList', () => {
  it('rozróżnia wiadomość użytkownika i asystenta', async () => {
    await renderList([
      chatMessage({ key: 'u1', id: 'u1', role: 'user', content: 'Pytanie' }),
      chatMessage(),
    ])

    expect(screen.getByTestId('message-user')).toHaveAccessibleName(USER_ROLE)
    expect(screen.getByTestId('message-assistant')).toHaveAccessibleName(ASSISTANT_ROLE)
    expect(screen.getByText('Pytanie')).toBeVisible()
    expect(screen.getByText('Odpowiedź')).toBeVisible()
  })

  it('przewija na dół przy dopisaniu wiadomości, gdy użytkownik jest przy dole', async () => {
    await renderList([chatMessage({ content: 'A' })])
    expect(scrollTo).toHaveBeenCalled()
  })

  it('pokazuje przycisk przewijania na dół po przewinięciu w górę i chowa go po kliknięciu', async () => {
    await renderList([chatMessage()])
    const container = screen.getByTestId('message-list')
    Object.defineProperty(container, 'scrollHeight', { value: 1000, configurable: true })
    Object.defineProperty(container, 'clientHeight', { value: 400, configurable: true })

    fireEvent.scroll(container)

    const button = await screen.findByRole('button', { name: SCROLL_DOWN })
    scrollTo.mockClear()
    await userEvent.setup().click(button)

    expect(scrollTo).toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByRole('button', { name: SCROLL_DOWN })).toBeNull())
  })

  it('pokazuje „Wygeneruj ponownie” tylko przy ostatniej wiadomości asystenta', async () => {
    const { onRegenerate } = await renderList([
      chatMessage({ key: 'u1', id: 'u1', role: 'user', content: 'Pytanie' }),
      chatMessage({ key: 'a1', id: 'a1', content: 'Pierwsza' }),
      chatMessage({ key: 'u2', id: 'u2', role: 'user', content: 'Drugie pytanie' }),
      chatMessage({ key: 'a2', id: 'a2', content: 'Druga' }),
    ])

    const [first, second] = screen.getAllByTestId('message-assistant')
    expect(within(first!).queryByRole('button', { name: REGENERATE })).toBeNull()

    await userEvent.setup().click(within(second!).getByRole('button', { name: REGENERATE }))
    expect(onRegenerate).toHaveBeenCalledTimes(1)
  })

  it('ukrywa „Wygeneruj ponownie” w trakcie streamu', async () => {
    await renderList([chatMessage({ status: 'streaming' })], { streaming: true })

    expect(screen.queryByRole('button', { name: REGENERATE })).toBeNull()
  })

  it('chipy dokumentów wołają onOpenDocument', async () => {
    const { onOpenDocument } = await renderList([
      chatMessage({ docAggs: [{ docId: 'd1', docName: 'Raport', count: 2 }] }),
    ])

    await userEvent.setup().click(screen.getByRole('button', { name: 'Raport (2)' }))

    expect(onOpenDocument).toHaveBeenCalledWith('d1', 'Raport')
  })

  it('wiadomość przerwana dostaje chip „Przerwano”', async () => {
    await renderList([chatMessage({ status: 'aborted' })])

    expect(screen.getByText('Przerwano')).toBeVisible()
  })

  it('wiadomość z błędem dostaje Alert z komunikatem błędu', async () => {
    await renderList([chatMessage({ status: 'error', error: 'Timeout modelu' })])

    expect(screen.getByRole('alert')).toHaveTextContent('Timeout modelu')
  })

  it('bez komunikatu błędu Alert pokazuje tekst z i18n', async () => {
    await renderList([chatMessage({ status: 'error', error: null })])

    expect(screen.getByRole('alert')).toHaveTextContent('Nie udało się uzyskać odpowiedzi.')
  })
})

/** Asystent, któremu test może zmienić status: stream → koniec (przykład z briefu T5b). */
function LiveAssistant() {
  const [status, setStatus] = useState<ChatMessage['status']>('streaming')
  return (
    <>
      <button onClick={() => setStatus('done')}>koniec</button>
      <AssistantMessage
        message={chatMessage({ status, thinking: 'Analiza' })}
        onOpenDocument={vi.fn()}
        onFeedback={vi.fn()}
      />
    </>
  )
}

describe('akordeon Myślenie', () => {
  it('jest rozwinięty w trakcie streamu i zwija się po końcu', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<LiveAssistant />)

    expect(screen.getByRole('button', { name: THINKING })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Analiza')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'koniec' }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: THINKING })).toHaveAttribute(
        'aria-expanded',
        'false',
      ),
    )
    await waitFor(() => expect(screen.getByText('Analiza')).not.toBeVisible())
  })

  it('historię z <think> pokazuje jako myślenie osobno od treści', async () => {
    const user = userEvent.setup()
    await renderWithProviders(
      <MessageList
        messages={[chatMessage({ content: 'Odpowiedź', thinking: 'Rozumowanie' })]}
        streaming={false}
        onOpenDocument={vi.fn()}
        onFeedback={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    )

    expect(screen.getByText('Odpowiedź')).toBeVisible()
    expect(screen.queryByText(/think/)).toBeNull()
    expect(screen.getByText('Rozumowanie')).not.toBeVisible()

    await user.click(screen.getByRole('button', { name: THINKING }))
    expect(screen.getByText('Rozumowanie')).toBeVisible()
  })
})
