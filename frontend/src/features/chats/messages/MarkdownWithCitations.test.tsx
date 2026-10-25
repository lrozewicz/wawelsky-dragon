import { useState } from 'react'
import type { JSX } from 'react'
import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import type { Citation } from '../../chat-stream/reducer'

import { MarkdownWithCitations } from './MarkdownWithCitations'

afterEach(cleanup)

/** Napisy z `locales/pl/*.json` — test chodzi na interfejsie polskim (domyślnym w `renderWithProviders`). */
const CHIP_LABEL = (n: number): string => `Cytowanie ${n}`
const DOC_NAME = 'Smok.pdf'

function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    chunkId: 'chunk-0',
    docId: 'doc-0',
    docName: DOC_NAME,
    content: 'Smok wawelski mieszkał pod Wawelem.',
    similarity: 0.5,
    ...overrides,
  }
}

async function renderMarkdown(text: string, citations: Citation[]) {
  const onOpenDocument = vi.fn()
  const result = await renderWithProviders(
    <MarkdownWithCitations text={text} citations={citations} onOpenDocument={onOpenDocument} />,
  )
  return { onOpenDocument, container: result.container }
}

describe('MarkdownWithCitations', () => {
  it('po re-renderze rodzica chip zachowuje węzeł DOM (stabilny `components`)', async () => {
    // `react-markdown` traktuje wpisy `components` jako typy elementów Reacta — niestabilna
    // tożsamość komponentu linku odmontowywałaby poddrzewo i chip traciłby węzeł DOM (MINOR
    // QA E5-H3 #7: fokus po Esc w podglądzie lądował na `body`, bo wyzwalacz znikał z DOM).

    function Harness(): JSX.Element {
      const [ticks, setTicks] = useState(0)
      return (
        <>
          <button onClick={() => setTicks(ticks + 1)}>rerender</button>
          {/* Świeża tablica, świeży obiekt cytowania i świeża funkcja przy każdym renderze —
              dokładnie jak `message.citations`/`onOpenDocument` w `MessageList`. */}
          <MarkdownWithCitations
            text="Smok [ID:0]."
            citations={[citation()]}
            onOpenDocument={vi.fn()}
          />
        </>
      )
    }

    const user = userEvent.setup()
    await renderWithProviders(<Harness />)
    const before = screen.getByRole('button', { name: CHIP_LABEL(1) })

    await user.click(screen.getByRole('button', { name: 'rerender' }))

    const after = screen.getByRole('button', { name: CHIP_LABEL(1) })
    expect(after.isConnected).toBe(true)
    expect(after).toBe(before)
  })

  it('zamienia znacznik w akapicie na chip o numerze n+1', async () => {
    await renderMarkdown('Smok [ID:0].', [citation()])

    expect(screen.getByRole('button', { name: CHIP_LABEL(1) })).toHaveTextContent('1')
    expect(screen.getByText(/Smok/)).toBeInTheDocument()
    expect(screen.queryByText(/\[ID:0\]/)).not.toBeInTheDocument()
  })

  it('numeruje chipy indeksem cytowania powiększonym o jeden', async () => {
    await renderMarkdown('Dwa smoki [ID:1].', [citation(), citation({ chunkId: 'chunk-1' })])

    expect(screen.getByRole('button', { name: CHIP_LABEL(2) })).toHaveTextContent('2')
  })

  it('zamienia znacznik w elemencie listy na chip', async () => {
    await renderMarkdown('- Smok\n- [ID:0]', [citation()])

    const chip = screen.getByRole('button', { name: CHIP_LABEL(1) })
    expect(chip.closest('li')).not.toBeNull()
  })

  it('znacznik w bloku kodu zostaje tekstem', async () => {
    await renderMarkdown('Tekst\n\n```\n[ID:0]\n```\n', [citation()])

    expect(screen.queryByRole('button', { name: CHIP_LABEL(1) })).not.toBeInTheDocument()
    expect(screen.getByText('[ID:0]')).toBeInTheDocument()
  })

  it('znacznik w kodzie inline zostaje tekstem', async () => {
    await renderMarkdown('`[ID:0]`', [citation()])

    expect(screen.queryByRole('button', { name: CHIP_LABEL(1) })).not.toBeInTheDocument()
    expect(screen.getByText('[ID:0]')).toBeInTheDocument()
  })

  it('znacznik poza zakresem cytowań nie tworzy chipa', async () => {
    await renderMarkdown('Smok [ID:9].', [citation()])

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByText(/\[ID:9\]/)).not.toBeInTheDocument()
  })

  it('linię zaczynającą się od tagu HTML renderuje jako tekst, a znacznik w niej nadal jako chip', async () => {
    await renderMarkdown('Na podstawie źródeł:\n<p>Wawelski smok [ID:0]', [citation()])

    expect(screen.getByText(/<p>Wawelski smok/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: CHIP_LABEL(1) })).toHaveTextContent('1')
  })

  it('tagi HTML w linii zostają tekstem, a znacznik nadal tworzy chip', async () => {
    const { container } = await renderMarkdown('A <b>x</b> [ID:0]', [citation()])

    expect(screen.getByText('A <b>x</b>')).toBeInTheDocument()
    expect(container.querySelector('b')).toBeNull()
    expect(screen.getByRole('button', { name: CHIP_LABEL(1) })).toHaveTextContent('1')
  })

  it('renderuje tabelę GFM, także ze znacznikiem w komórce', async () => {
    await renderMarkdown('| A | B |\n| --- | --- |\n| [ID:0] | 2 |', [citation()])

    const table = screen.getByRole('table')
    expect(screen.getByRole('cell', { name: '2' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: CHIP_LABEL(1) }).closest('td')).not.toBeNull()
    expect(table).toBeInTheDocument()
  })

  it('zwykły link otwiera się w nowej karcie z rel="noopener noreferrer"', async () => {
    await renderMarkdown('[Google](https://example.com)', [])

    const link = screen.getByRole('link', { name: 'Google' })
    expect(link).toHaveAttribute('href', 'https://example.com')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('nie zostawia w DOM adresu cite:', async () => {
    await renderMarkdown('Smok [ID:0].', [citation()])

    expect(document.querySelector('a[href^="cite:"]')).toBeNull()
  })

  it('ręcznie wpisany link cite: poza zakresem cytowań zostaje tekstem', async () => {
    await renderMarkdown('[sfałszowany](cite:7)', [citation()])

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('sfałszowany')).toBeInTheDocument()
  })

  it('klik w chip otwiera dialog, a „Otwórz dokument” woła onOpenDocument', async () => {
    const { onOpenDocument } = await renderMarkdown('Smok [ID:0].', [citation()])
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: CHIP_LABEL(1) }))
    await user.click(await screen.findByRole('button', { name: 'Otwórz dokument' }))

    expect(onOpenDocument).toHaveBeenCalledWith('doc-0', DOC_NAME)
  })
})
