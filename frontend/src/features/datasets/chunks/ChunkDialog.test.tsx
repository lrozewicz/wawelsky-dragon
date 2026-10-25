/**
 * Testy `ChunkDialog` (kontrakt WP E3-4a §ChunkDialog): tryb nowy (puste pola, walidacja treści po
 * `trim`, dodanie słowa kluczowego wpisaniem + Enter), tryb edycji (wartości początkowe, typ
 * read-only, zmiana „Włączony”), blokada „Zapisz” przy `saving`, „Anuluj” i reset pól przy
 * ponownym otwarciu. Przykłady wejście → wyjście z briefu T2 są przepisane dosłownie.
 */

import { useState } from 'react'
import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fixtureChunk } from '../../../test/msw/handlers'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { ChunkDialog } from './ChunkDialog'
import type { ChunkFormValues } from './chunkSchema'
import type { Chunk } from './queries'

afterEach(cleanup)

type HarnessProps = {
  chunk?: Chunk | null
  saving?: boolean
  onSubmit?: (values: ChunkFormValues) => void
  onClose?: () => void
}

/** Okno da się zamykać i otwierać — potrzebne do sprawdzenia resetu pól przy ponownym otwarciu. */
function Harness({ chunk = null, saving = false, onSubmit, onClose }: HarnessProps) {
  const [open, setOpen] = useState(true)
  return (
    <>
      {/* MUI oznacza treść poza oknem jako `aria-hidden`, więc przełącznik znajdujemy po testid. */}
      <button type="button" data-testid="toggle" onClick={() => setOpen((value) => !value)}>
        toggle
      </button>
      <ChunkDialog
        open={open}
        chunk={chunk}
        saving={saving}
        onClose={() => {
          onClose?.()
          setOpen(false)
        }}
        onSubmit={onSubmit ?? (() => undefined)}
      />
    </>
  )
}

function contentInput(): HTMLElement {
  return screen.getByTestId('chunk-dialog-content')
}

/** Okno otwarte na stałe, ale z możliwością podmiany `chunk` — test resetu przy zmianie chunku. */
function ChunkSwitchHarness({ first, second }: { first: Chunk; second: Chunk }) {
  const [chunk, setChunk] = useState(first)
  return (
    <>
      <button type="button" data-testid="second" onClick={() => setChunk(second)}>
        second
      </button>
      <ChunkDialog
        open
        chunk={chunk}
        saving={false}
        onClose={() => undefined}
        onSubmit={() => undefined}
      />
    </>
  )
}

/** Pole `Autocomplete` ma rolę `combobox` (jego wewnętrzny `input`), nie `textbox`. */
function tagsInput(testId: string): HTMLElement {
  return within(screen.getByTestId(testId)).getByRole('combobox')
}

/** `data-testid` `Switch`a siedzi na jego korzeniu, więc stan czytamy z wewnętrznego `input`. */
function availableSwitch(): HTMLElement {
  return within(screen.getByTestId('chunk-dialog-available')).getByRole('switch')
}

describe('ChunkDialog', () => {
  it('tryb nowy: tytuł, puste pola, domyślnie włączony i brak typu', async () => {
    await renderWithProviders(<Harness />)

    expect(screen.getByTestId('chunk-dialog')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveTextContent('Nowy chunk')
    expect(contentInput()).toHaveValue('')
    expect(availableSwitch()).toBeChecked()
    expect(screen.queryByLabelText('Typ')).not.toBeInTheDocument()
  })

  it('treść z samych spacji pokazuje komunikat i nie woła `onSubmit`', async () => {
    const onSubmit = vi.fn()
    await renderWithProviders(<Harness onSubmit={onSubmit} />)
    const user = userEvent.setup()

    await user.type(contentInput(), '   ')
    await user.click(screen.getByTestId('chunk-dialog-save'))

    expect(screen.getByText('Treść jest wymagana')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('całkiem pusta treść pokazuje komunikat (formularz bez natywnej walidacji)', async () => {
    const onSubmit = vi.fn()
    await renderWithProviders(<Harness onSubmit={onSubmit} />)
    const user = userEvent.setup()

    // jsdom nie implementuje natywnej walidacji, więc blokadę przeglądarki zastępuje asercja
    // atrybutu `novalidate` — bez niego `required` blokuje `submit` i komunikat się nie pokazuje.
    expect(screen.getByTestId('chunk-dialog').querySelector('form')).toHaveAttribute('novalidate')

    await user.click(screen.getByTestId('chunk-dialog-save'))

    expect(screen.getByText('Treść jest wymagana')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('zapis nowego chunku wysyła treść przyciętą i słowo kluczowe dodane Enterem', async () => {
    const onSubmit = vi.fn()
    await renderWithProviders(<Harness onSubmit={onSubmit} />)
    const user = userEvent.setup()

    await user.type(contentInput(), '  abc  ')
    await user.type(tagsInput('chunk-dialog-keywords'), 'x{Enter}')

    expect(within(screen.getByTestId('chunk-dialog-keywords')).getByText('x')).toBeInTheDocument()

    await user.click(screen.getByTestId('chunk-dialog-save'))

    expect(onSubmit).toHaveBeenCalledWith({
      content: 'abc',
      important_keywords: ['x'],
      questions: [],
      available: true,
    })
  })

  it('tryb edycji: wartości początkowe, typ read-only i switch z chunku', async () => {
    const onSubmit = vi.fn()
    const chunk = fixtureChunk({
      content: 'Stara treść',
      available: false,
      doc_type_kwd: 'table',
      important_keywords: ['a'],
      questions: ['q?'],
    })
    await renderWithProviders(<Harness chunk={chunk} onSubmit={onSubmit} />)

    expect(screen.getByRole('dialog')).toHaveTextContent('Edytuj chunk')
    expect(contentInput()).toHaveValue('Stara treść')
    expect(screen.getByLabelText('Typ')).toBeDisabled()
    expect(screen.getByLabelText('Typ')).toHaveValue('Tabela')
    expect(availableSwitch()).not.toBeChecked()
  })

  it('włączenie chunku w edycji trafia do `onSubmit`', async () => {
    const onSubmit = vi.fn()
    const chunk = fixtureChunk({ content: 'Stara treść', available: false })
    await renderWithProviders(<Harness chunk={chunk} onSubmit={onSubmit} />)
    const user = userEvent.setup()

    await user.click(availableSwitch())
    await user.click(screen.getByTestId('chunk-dialog-save'))

    expect(onSubmit).toHaveBeenCalledWith({
      content: 'Stara treść',
      important_keywords: [],
      questions: [],
      available: true,
    })
  })

  it('edytuje listę pytań i pokazuje podpowiedź', async () => {
    const onSubmit = vi.fn()
    await renderWithProviders(<Harness onSubmit={onSubmit} />)
    const user = userEvent.setup()

    expect(
      screen.getByText('Jeśli podano pytania, embedding chunku powstaje z nich'),
    ).toBeInTheDocument()

    await user.type(contentInput(), 't')
    await user.type(tagsInput('chunk-dialog-questions'), 'Po co?{Enter}')
    await user.click(screen.getByTestId('chunk-dialog-save'))

    expect(onSubmit).toHaveBeenCalledWith({
      content: 't',
      important_keywords: [],
      questions: ['Po co?'],
      available: true,
    })
  })

  it('`saving` blokuje „Zapisz”', async () => {
    await renderWithProviders(<Harness saving />)

    expect(screen.getByTestId('chunk-dialog-save')).toBeDisabled()
  })

  it('„Anuluj” woła `onClose`', async () => {
    const onClose = vi.fn()
    await renderWithProviders(<Harness onClose={onClose} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('po ponownym otwarciu pola wracają do wartości początkowych', async () => {
    await renderWithProviders(<Harness />)
    const user = userEvent.setup()

    await user.type(contentInput(), 'cokolwiek')
    await user.click(screen.getByTestId('toggle'))
    await user.click(screen.getByTestId('toggle'))

    expect(contentInput()).toHaveValue('')
  })

  it('edytuje pole tekstowe, gdy `doc_type_kwd` jest pusty', async () => {
    const chunk = fixtureChunk({ doc_type_kwd: '' })
    await renderWithProviders(<Harness chunk={chunk} />)

    expect(screen.getByLabelText('Typ')).toBeDisabled()
    expect(screen.getByLabelText('Typ')).toHaveValue('Tekst')
  })

  it('podmiana chunku odświeża wartości początkowe pól', async () => {
    const user = userEvent.setup()
    await renderWithProviders(
      <ChunkSwitchHarness
        first={fixtureChunk({ id: 'c1', content: 'Treść A', available: true })}
        second={fixtureChunk({ id: 'c2', content: 'Treść B', available: false })}
      />,
    )

    expect(contentInput()).toHaveValue('Treść A')
    await user.type(contentInput(), ' dopisek')

    await user.click(screen.getByTestId('second'))

    expect(contentInput()).toHaveValue('Treść B')
    expect(availableSwitch()).not.toBeChecked()
  })
})
