import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { fixtureRetrievalChunk } from '../../../test/msw/handlers/retrieval'
import type { RetrievalChunk } from '../../datasets/retrieval/queries'

import { HitsList } from './HitsList'

afterEach(cleanup)

/** Etykiety z `locales/pl/searches.json` — test chodzi na interfejsie polskim. */
const EMPTY = 'Brak wyników.'
const OPEN_DOC = 'Otwórz dokument plik.pdf'

type HitsListProps = Parameters<typeof HitsList>[0]

async function renderHits(overrides: Partial<HitsListProps> = {}) {
  const onOpenDocument = vi.fn()
  const props: HitsListProps = {
    chunks: [],
    question: '',
    onOpenDocument,
    ...overrides,
  }

  const view = await renderWithProviders(<HitsList {...props} />)

  return { ...view, onOpenDocument }
}

/** Chunk z podanym `highlight` i/lub `content`. */
function chunk(overrides: Partial<RetrievalChunk> = {}): RetrievalChunk {
  return fixtureRetrievalChunk(overrides)
}

describe('HitsList', () => {
  it('bez trafień pokazuje komunikat o braku wyników', async () => {
    await renderHits()

    expect(screen.getByText(EMPTY)).toBeInTheDocument()
  })

  it('nazwa dokumentu jest przyciskiem otwierającym dokument', async () => {
    const { onOpenDocument } = await renderHits({ chunks: [chunk()] })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: OPEN_DOC }))

    expect(onOpenDocument).toHaveBeenCalledWith('doc-1', 'plik.pdf')
  })

  it('rozbija highlight po <em> — trafienie w elemencie mark, reszta tekstem', async () => {
    const { container } = await renderHits({
      chunks: [chunk({ highlight: 'ala <em>ma</em> kota' })],
    })

    const mark = screen.getByText('ma')
    expect(mark.tagName).toBe('MARK')
    expect(container.textContent).toContain('ala ma kota')
  })

  it('obsługuje też znacznik <mark> z backendu', async () => {
    await renderHits({ chunks: [chunk({ highlight: 'a <mark>smok</mark> b' })] })

    expect(screen.getByText('smok').tagName).toBe('MARK')
  })

  it('nie wstrzykuje HTML z highlight — obcy tag znika, tekst zostaje', async () => {
    const { container } = await renderHits({
      chunks: [chunk({ highlight: '<script>x</script>' })],
    })

    expect(container.querySelector('script')).toBeNull()
    expect(container.textContent).toContain('x')
  })

  it('bez highlight pokazuje content i podświetla słowa pytania (≥3 znaki, bez wielkości liter)', async () => {
    const { container } = await renderHits({
      chunks: [chunk({ content: 'Ala ma kota', highlight: null })],
      question: 'ala smok',
    })

    const mark = screen.getByText('Ala')
    expect(mark.tagName).toBe('MARK')
    expect(container.textContent).toContain('Ala ma kota')
  })

  it('bez highlight i z krótkim pytaniem (<3 znaki) nie podświetla niczego', async () => {
    const { container } = await renderHits({
      chunks: [chunk({ content: 'Ala ma kota', highlight: null })],
      question: 'ma',
    })

    expect(container.querySelectorAll('mark')).toHaveLength(0)
    expect(container.textContent).toContain('Ala ma kota')
  })
})
