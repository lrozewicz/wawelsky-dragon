/**
 * Testy `RowActionsMenu` (kontrakt WP E3-7 §C2): klik ⋮ otwiera menu, klik pozycji woła
 * `onClick` i zamyka menu, Esc zamyka, pozycja `disabled` nie woła `onClick`.
 */

import { cleanup, fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../test/renderWithProviders'

import { RowActionsMenu } from './RowActionsMenu'
import type { RowActionItem } from './RowActionsMenu'

afterEach(cleanup)

function item(overrides: Partial<RowActionItem> & { key: string }): RowActionItem {
  return { label: overrides.key, onClick: vi.fn(), ...overrides }
}

describe('RowActionsMenu', () => {
  it('klik ⋮ otwiera menu z pozycjami', async () => {
    const user = userEvent.setup()
    await renderWithProviders(
      <RowActionsMenu
        items={[item({ key: 'rename' }), item({ key: 'delete' })]}
        ariaLabel="Akcje wiersza"
      />,
    )

    expect(screen.queryByTestId('row-action-rename')).not.toBeInTheDocument()
    await user.click(screen.getByTestId('row-actions-menu'))

    expect(await screen.findByTestId('row-action-rename')).toBeInTheDocument()
    expect(screen.getByTestId('row-action-delete')).toBeInTheDocument()
  })

  it('klik pozycji woła onClick i zamyka menu', async () => {
    const onClick = vi.fn()
    const user = userEvent.setup()
    await renderWithProviders(
      <RowActionsMenu items={[item({ key: 'rename', onClick })]} ariaLabel="Akcje wiersza" />,
    )

    await user.click(screen.getByTestId('row-actions-menu'))
    await user.click(await screen.findByTestId('row-action-rename'))

    expect(onClick).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('row-action-rename')).not.toBeInTheDocument()
  })

  it('Esc zamyka menu', async () => {
    const user = userEvent.setup()
    await renderWithProviders(
      <RowActionsMenu items={[item({ key: 'rename' })]} ariaLabel="Akcje wiersza" />,
    )

    await user.click(screen.getByTestId('row-actions-menu'))
    expect(await screen.findByTestId('row-action-rename')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('row-action-rename')).not.toBeInTheDocument()
  })

  it('pozycja disabled nie woła onClick', async () => {
    const onClick = vi.fn()
    const user = userEvent.setup()
    await renderWithProviders(
      <RowActionsMenu
        items={[item({ key: 'preview', onClick, disabled: true })]}
        ariaLabel="Akcje wiersza"
      />,
    )

    await user.click(screen.getByTestId('row-actions-menu'))
    const disabledItem = await screen.findByTestId('row-action-preview')
    expect(disabledItem).toHaveAttribute('aria-disabled', 'true')

    // `userEvent` blokuje klik w element z `pointer-events: none`; `fireEvent` oddaje zdarzenie
    // wprost, więc sprawdzamy, że MUI i tak nie woła handlera.
    fireEvent.click(disabledItem)
    expect(onClick).not.toHaveBeenCalled()
  })
})
