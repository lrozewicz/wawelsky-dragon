import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { AssistantMessage } from './AssistantMessage'
import type { AssistantMessageProps } from './AssistantMessage'
import type { ChatMessage } from '../sessions/chatMessages'

afterEach(cleanup)

/** Napisy z `locales/pl/*.json` — test chodzi na interfejsie polskim. */
const COPY = 'Kopiuj'
const COPIED = 'Skopiowano do schowka.'
const COPY_FAILED = 'Nie udało się skopiować — zaznacz tekst i skopiuj ręcznie (Ctrl+C)'
const THUMB_UP = 'Odpowiedź pomocna'
const THUMB_DOWN = 'Odpowiedź niepomocna'
const REGENERATE = 'Wygeneruj ponownie'
const FEEDBACK_TITLE = 'Co było nie tak?'
const FEEDBACK_LABEL = 'Uzasadnienie'
const FEEDBACK_SEND = 'Wyślij'

function chatMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    key: 'a1',
    id: 'a1',
    role: 'assistant',
    content: 'Treść odpowiedzi',
    thinking: '',
    citations: [],
    docAggs: [],
    thumbup: null,
    status: 'done',
    error: null,
    ...overrides,
  }
}

async function renderAssistant(overrides: Partial<AssistantMessageProps> = {}) {
  const onOpenDocument = vi.fn()
  const onFeedback = vi.fn()
  const onRegenerate = vi.fn()
  await renderWithProviders(
    <AssistantMessage
      message={chatMessage()}
      onOpenDocument={onOpenDocument}
      onFeedback={onFeedback}
      onRegenerate={onRegenerate}
      {...overrides}
    />,
  )
  return { onOpenDocument, onFeedback, onRegenerate }
}

describe('AssistantMessage', () => {
  it('Kopiuj zapisuje treść w schowku i potwierdza to Snackbarem', async () => {
    await renderAssistant()

    // `userEvent` podstawia własny schowek (`navigator.clipboard`) — tekst czytamy z niego.
    await userEvent.setup().click(screen.getByRole('button', { name: COPY }))

    await expect(navigator.clipboard.readText()).resolves.toBe('Treść odpowiedzi')
    expect(await screen.findByText(COPIED)).toBeVisible()
  })

  it('bez navigator.clipboard (HTTP) i bez execCommand: brak fałszywego „Skopiowano”', async () => {
    await renderAssistant()
    const user = userEvent.setup()
    // Stos testowy po HTTP: `navigator.clipboard` nie istnieje; jsdom nie ma też `execCommand`,
    // więc kopiowanie się nie udaje — potwierdzenie nie może się pokazać (brief E6-2 T9).
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })

    await user.click(screen.getByRole('button', { name: COPY }))

    expect(screen.queryByText(COPIED)).toBeNull()
    // SC-E5-H9-08: porażka dostaje czytelny komunikat (w treści wiadomości, nie tylko milczenie).
    expect(await screen.findByTestId('message-copy-error')).toHaveTextContent(COPY_FAILED)
    Reflect.deleteProperty(navigator, 'clipboard')
  })

  it('👍 zgłasza pozytywny feedback bez uzasadnienia', async () => {
    const { onFeedback } = await renderAssistant()

    await userEvent.setup().click(screen.getByRole('button', { name: THUMB_UP }))

    expect(onFeedback).toHaveBeenCalledWith(expect.objectContaining({ id: 'a1' }), true, null)
  })

  it('zaznacza aktywny przycisk zgodnie z message.thumbup', async () => {
    await renderAssistant({ message: chatMessage({ thumbup: true }) })

    expect(screen.getByRole('button', { name: THUMB_UP })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: THUMB_DOWN })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('👎 otwiera okno uzasadnienia i wysyła wpisany tekst', async () => {
    const { onFeedback } = await renderAssistant()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: THUMB_DOWN }))
    expect(screen.getByText(FEEDBACK_TITLE)).toBeVisible()

    await user.type(screen.getByLabelText(FEEDBACK_LABEL), 'Za krótka odpowiedź')
    await user.click(screen.getByRole('button', { name: FEEDBACK_SEND }))

    expect(onFeedback).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'a1' }),
      false,
      'Za krótka odpowiedź',
    )
    expect(screen.queryByText(FEEDBACK_TITLE)).toBeNull()
  })

  it('wywołuje „Wygeneruj ponownie”, gdy je dostanie', async () => {
    const { onRegenerate } = await renderAssistant()

    await userEvent.setup().click(screen.getByRole('button', { name: REGENERATE }))

    expect(onRegenerate).toHaveBeenCalledTimes(1)
  })

  it('prologue ma tylko Kopiuj', async () => {
    await renderAssistant({ message: chatMessage({ key: 'greeting', id: null }) })

    expect(screen.getByRole('button', { name: COPY })).toBeVisible()
    expect(screen.queryByRole('button', { name: THUMB_UP })).toBeNull()
    expect(screen.queryByRole('button', { name: THUMB_DOWN })).toBeNull()
    expect(screen.queryByRole('button', { name: REGENERATE })).toBeNull()
  })
})
