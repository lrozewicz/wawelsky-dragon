/**
 * Testy `ChunkCard` (kontrakt WP E3-4a §T3): treść (markdown albo tabela) z badge'em typu,
 * zaznaczenie z klawiatury, przełącznik dostępności i wejście w edycję — a klik w kontrolki
 * nie wchodzi w podgląd karty.
 */

import { cleanup, fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { ChunkCard } from './ChunkCard'
import type { ChunkCardProps } from './ChunkCard'
import type { Chunk } from './queries'

afterEach(cleanup)

/** Fixture chunku: pełny kształt `Chunk` (12 pól), nadpisywany tylko tam, gdzie test tego chce. */
function makeChunk(overrides: Partial<Chunk> = {}): Chunk {
  return {
    id: 'c1',
    content: 'treść chunku',
    available: true,
    doc_type_kwd: 'text',
    docnm_kwd: 'doc.pdf',
    document_id: 'd1',
    dataset_id: 'ds1',
    image_id: '',
    important_keywords: [],
    questions: [],
    tag_kwd: [],
    positions: [],
    ...overrides,
  }
}

async function renderCard(chunk: Chunk, props: Partial<ChunkCardProps> = {}) {
  const spies = {
    onToggleSelect: vi.fn<(id: string) => void>(),
    onToggleAvailable: vi.fn<(id: string, available: boolean) => void>(),
    onActivate: vi.fn<(chunk: Chunk) => void>(),
    onEdit: vi.fn<(chunk: Chunk) => void>(),
  }
  const result = await renderWithProviders(
    <ChunkCard chunk={chunk} selected={false} expanded active={false} {...spies} {...props} />,
  )
  return { spies, ...result }
}

describe('ChunkCard', () => {
  it('renderuje treść markdown i badge typu', async () => {
    await renderCard(makeChunk({ content: '**pogrubienie** w treści' }))

    expect(screen.getByText('pogrubienie')).toBeInTheDocument()
    expect(screen.getByTestId('chunk-card-c1')).toHaveTextContent('Tekst')
  })

  it('pusty i nieznany typ dostaje badge „Tekst”', async () => {
    await renderCard(makeChunk({ doc_type_kwd: '' }))
    expect(screen.getByText('Tekst')).toBeInTheDocument()

    cleanup()
    await renderCard(makeChunk({ doc_type_kwd: 'nieznany' }))
    expect(screen.getByText('Tekst')).toBeInTheDocument()
  })

  it('typ table renderuje tabelę HTML', async () => {
    await renderCard(
      makeChunk({ doc_type_kwd: 'table', content: '<table><tr><td>A</td></tr></table>' }),
    )

    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('cell')).toHaveTextContent('A')
  })

  it('Enter i Spacja na karcie przełączają zaznaczenie', async () => {
    const chunk = makeChunk()
    const { spies } = await renderCard(chunk)
    const card = screen.getByTestId('chunk-card-c1')

    fireEvent.keyDown(card, { key: 'Enter' })
    fireEvent.keyDown(card, { key: ' ' })

    expect(spies.onToggleSelect).toHaveBeenCalledTimes(2)
    expect(spies.onToggleSelect).toHaveBeenCalledWith('c1')
    expect(spies.onActivate).not.toHaveBeenCalled()
  })

  it('checkbox zaznacza chunk i nie wchodzi w podgląd karty', async () => {
    const { spies } = await renderCard(makeChunk())

    await userEvent.setup().click(screen.getByRole('checkbox', { name: 'Zaznacz chunk' }))

    expect(spies.onToggleSelect).toHaveBeenCalledWith('c1')
    expect(spies.onActivate).not.toHaveBeenCalled()
  })

  it('Switch woła onToggleAvailable z odwróconą wartością', async () => {
    const { spies } = await renderCard(makeChunk({ available: true }))

    await userEvent.setup().click(screen.getByRole('switch', { name: 'Chunk włączony' }))

    expect(spies.onToggleAvailable).toHaveBeenCalledWith('c1', false)
  })

  it('klik w Switch nie woła onActivate', async () => {
    const { spies } = await renderCard(makeChunk())

    await userEvent.setup().click(screen.getByTestId('chunk-switch-c1'))

    expect(spies.onActivate).not.toHaveBeenCalled()
  })

  it('klik w kartę woła onActivate, a dwuklik onEdit', async () => {
    const chunk = makeChunk()
    const { spies } = await renderCard(chunk)
    const card = screen.getByTestId('chunk-card-c1')

    await userEvent.setup().click(card)
    fireEvent.doubleClick(card)

    expect(spies.onActivate).toHaveBeenCalledWith(chunk)
    expect(spies.onEdit).toHaveBeenCalledWith(chunk)
  })

  it('przycisk Edytuj woła onEdit i nie wchodzi w podgląd karty', async () => {
    const chunk = makeChunk()
    const { spies } = await renderCard(chunk)

    await userEvent.setup().click(screen.getByTestId('chunk-edit-c1'))

    expect(spies.onEdit).toHaveBeenCalledWith(chunk)
    expect(spies.onActivate).not.toHaveBeenCalled()
  })

  it('słowa kluczowe pokazują się jako chipy, puste nie tworzą listy', async () => {
    const { unmount } = await renderCard(makeChunk({ important_keywords: ['alfa', 'beta'] }))

    expect(screen.getByText('alfa')).toBeInTheDocument()
    expect(screen.getByText('beta')).toBeInTheDocument()
    unmount()

    await renderCard(makeChunk())
    expect(screen.queryByLabelText('Słowa kluczowe')).not.toBeInTheDocument()
  })

  it('tryb skrócony i wyłączony chunk nadal pokazują treść', async () => {
    await renderCard(makeChunk({ available: false, content: 'wyłączony chunk' }), {
      expanded: false,
      selected: true,
    })

    expect(screen.getByText('wyłączony chunk')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Zaznacz chunk' })).toBeChecked()
  })
})
