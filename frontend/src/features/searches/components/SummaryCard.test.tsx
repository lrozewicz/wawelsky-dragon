import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { initialStreamState } from '../../chat-stream/reducer'
import type { Citation, StreamState } from '../../chat-stream/reducer'
import type { StreamPhase } from '../../chats/stream/useChatStream'

import { SummaryCard } from './SummaryCard'

afterEach(cleanup)

// Napisy z `locales/pl/searches.json` — test chodzi na interfejsie polskim (domyślnym).
const TITLE = 'Podsumowanie'
const LOADING = 'Generowanie podsumowania…'
const EXPAND = 'Rozwiń podsumowanie'
const COLLAPSE = 'Zwiń podsumowanie'

function streamState(overrides: Partial<StreamState> = {}): StreamState {
  return {
    ...initialStreamState,
    status: 'done',
    answer: 'Smok mieszkał pod Wawelem.',
    ...overrides,
  }
}

function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    chunkId: 'chunk-0',
    docId: 'doc-0',
    docName: 'Smok.pdf',
    content: 'Smok wawelski.',
    similarity: 0.5,
    ...overrides,
  }
}

async function renderCard(
  phase: StreamPhase,
  state: StreamState,
  onOpenDocument = vi.fn(),
): Promise<{ onOpenDocument: ReturnType<typeof vi.fn> }> {
  await renderWithProviders(
    <SummaryCard phase={phase} state={state} onOpenDocument={onOpenDocument} />,
  )
  return { onOpenDocument }
}

describe('SummaryCard', () => {
  it('pokazuje tytuł i treść odpowiedzi', async () => {
    await renderCard('done', streamState())

    expect(screen.getByText(TITLE)).toBeInTheDocument()
    expect(screen.getByText(/Smok mieszkał pod Wawelem/)).toBeInTheDocument()
  })

  it('renderuje cytowania z odpowiedzi jako chip otwierający dokument', async () => {
    const { onOpenDocument } = await renderCard(
      'done',
      streamState({ answer: 'Smok [ID:0].', citations: [citation()] }),
    )
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Cytowanie 1' }))
    await user.click(await screen.findByRole('button', { name: 'Otwórz dokument' }))

    expect(onOpenDocument).toHaveBeenCalledWith('doc-0', 'Smok.pdf')
  })

  it('w trakcie streamu bez tekstu pokazuje „Generowanie…”', async () => {
    await renderCard('streaming', streamState({ status: 'streaming', answer: '' }))

    expect(screen.getByText(LOADING)).toBeInTheDocument()
  })

  it('błąd pokazuje Alert z komunikatem błędu', async () => {
    await renderCard('error', streamState({ status: 'error', answer: '', error: 'limit modelu' }))

    expect(screen.getByRole('alert')).toHaveTextContent('limit modelu')
  })

  it('zwija treść do 208 px, a przycisk rozwija i zwija', async () => {
    await renderCard('done', streamState())
    const user = userEvent.setup()

    expect(screen.getByTestId('summary-content')).toHaveStyle({
      maxHeight: '208px',
      overflow: 'hidden',
    })

    await user.click(screen.getByRole('button', { name: EXPAND }))

    expect(screen.getByTestId('summary-content')).not.toHaveStyle({ maxHeight: '208px' })

    await user.click(screen.getByRole('button', { name: COLLAPSE }))

    expect(screen.getByTestId('summary-content')).toHaveStyle({ maxHeight: '208px' })
  })

  it('bez treści nie ma przycisku zwijania', async () => {
    await renderCard('streaming', streamState({ status: 'streaming', answer: '' }))

    expect(screen.queryByRole('button', { name: EXPAND })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: COLLAPSE })).not.toBeInTheDocument()
  })
})
