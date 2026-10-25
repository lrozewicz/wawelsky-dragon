/**
 * Testy `FilesBulkBar` (kontrakt WP E4-5c §7 p. 2): pasek widoczny tylko przy niepustym
 * zaznaczeniu, tekst licznika, przyciski Połącz/Przenieś/Usuń (z blokadą Połącz dla samych
 * folderów) i przycisk czyszczenia zaznaczenia.
 */

import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { FilesBulkBar } from './FilesBulkBar'
import type { FilesBulkBarProps } from './FilesBulkBar'

afterEach(cleanup)

function barProps(overrides: Partial<FilesBulkBarProps> = {}): FilesBulkBarProps {
  return {
    count: 2,
    linkDisabled: false,
    onLink: vi.fn(),
    onMove: vi.fn(),
    onDelete: vi.fn(),
    onClear: vi.fn(),
    ...overrides,
  }
}

describe('FilesBulkBar', () => {
  it('brak zaznaczenia nie renderuje paska', async () => {
    const props = barProps({ count: 0 })

    await renderWithProviders(<FilesBulkBar {...props} />)

    expect(screen.queryByTestId('files-bulk-bar')).not.toBeInTheDocument()
  })

  it('pokazuje licznik i przyciski akcji zbiorczych', async () => {
    const props = barProps()

    await renderWithProviders(<FilesBulkBar {...props} />)

    const bar = screen.getByTestId('files-bulk-bar')
    expect(within(bar).getByText('Zaznaczono 2 pliki')).toBeInTheDocument()
    expect(within(bar).getByTestId('files-bulk-link')).toHaveTextContent('Połącz')
    expect(within(bar).getByTestId('files-bulk-move')).toHaveTextContent('Przenieś')
    expect(within(bar).getByTestId('files-bulk-delete')).toHaveTextContent('Usuń')
  })

  it('blokuje Połącz, gdy zaznaczone są same foldery', async () => {
    const props = barProps({ linkDisabled: true })

    await renderWithProviders(<FilesBulkBar {...props} />)

    expect(screen.getByTestId('files-bulk-link')).toBeDisabled()
    expect(screen.getByTestId('files-bulk-move')).toBeEnabled()
  })

  it('przyciski wołają swoje akcje, a czyszczenie zaznaczenia ma etykietę Anuluj', async () => {
    const props = barProps()
    const user = userEvent.setup()

    await renderWithProviders(<FilesBulkBar {...props} />)

    await user.click(screen.getByTestId('files-bulk-link'))
    await user.click(screen.getByTestId('files-bulk-move'))
    await user.click(screen.getByTestId('files-bulk-delete'))
    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(props.onLink).toHaveBeenCalledTimes(1)
    expect(props.onMove).toHaveBeenCalledTimes(1)
    expect(props.onDelete).toHaveBeenCalledTimes(1)
    expect(props.onClear).toHaveBeenCalledTimes(1)
  })
})
