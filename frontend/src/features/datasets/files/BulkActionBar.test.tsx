/**
 * Testy `BulkActionBar` (kontrakt WP E3-3b §T6): pasek pojawia się tylko przy niepustym
 * zaznaczeniu, pokazuje jego liczbę i woła właściwy callback dla każdej z pięciu akcji oraz dla
 * wyczyszczenia zaznaczenia.
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { BulkActionBar } from './BulkActionBar'
import type { BulkActionBarProps } from './BulkActionBar'

afterEach(cleanup)

type Spies = Record<
  'onParse' | 'onCancel' | 'onEnable' | 'onDisable' | 'onDelete' | 'onClear',
  () => void
>

function handlers(): Spies {
  return {
    onParse: vi.fn<() => void>(),
    onCancel: vi.fn<() => void>(),
    onEnable: vi.fn<() => void>(),
    onDisable: vi.fn<() => void>(),
    onDelete: vi.fn<() => void>(),
    onClear: vi.fn<() => void>(),
  }
}

function renderBar(count: number, props: Partial<BulkActionBarProps> = {}) {
  const spies = handlers()
  return renderWithProviders(<BulkActionBar count={count} {...spies} {...props} />)
}

describe('BulkActionBar', () => {
  it('nie renderuje niczego bez zaznaczenia', async () => {
    await renderBar(0)
    expect(screen.queryByTestId('bulk-bar')).not.toBeInTheDocument()
  })

  it('pokazuje liczbę zaznaczonych dokumentów', async () => {
    await renderBar(3)
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('Zaznaczono: 3')
  })

  it('każdy przycisk woła swój callback, a „Wyczyść zaznaczenie” czyści', async () => {
    const spies = handlers()
    await renderWithProviders(<BulkActionBar count={3} {...spies} />)
    const user = userEvent.setup()

    await user.click(screen.getByTestId('bulk-parse'))
    await user.click(screen.getByTestId('bulk-cancel'))
    await user.click(screen.getByTestId('bulk-enable'))
    await user.click(screen.getByTestId('bulk-disable'))
    await user.click(screen.getByTestId('bulk-delete'))
    await user.click(screen.getByRole('button', { name: 'Wyczyść zaznaczenie' }))

    expect(spies.onParse).toHaveBeenCalledTimes(1)
    expect(spies.onCancel).toHaveBeenCalledTimes(1)
    expect(spies.onEnable).toHaveBeenCalledTimes(1)
    expect(spies.onDisable).toHaveBeenCalledTimes(1)
    expect(spies.onDelete).toHaveBeenCalledTimes(1)
    expect(spies.onClear).toHaveBeenCalledTimes(1)
  })

  it('ikony mają dostępne nazwy z i18n', async () => {
    await renderBar(2)
    expect(screen.getByRole('button', { name: 'Parsuj' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Anuluj parsowanie' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Włącz' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Wyłącz' })).toBeInTheDocument()
  })
})
