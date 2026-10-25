/**
 * Testy `SelectionBar` (kontrakt WP E3-4a §T3): pasek jest ukryty bez zaznaczenia, a przy
 * niepustym pokazuje liczbę i woła właściwy callback każdej akcji; etykieta „Zaznacz stronę”
 * zmienia się na „Odznacz stronę”, gdy cała strona jest już zaznaczona.
 */

import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { SelectionBar } from './SelectionBar'
import type { SelectionBarProps } from './SelectionBar'

afterEach(cleanup)

function handlers() {
  return {
    onTogglePage: vi.fn<() => void>(),
    onEnable: vi.fn<() => void>(),
    onDisable: vi.fn<() => void>(),
    onDelete: vi.fn<() => void>(),
  }
}

async function renderBar(props: Partial<SelectionBarProps> = {}) {
  const spies = handlers()
  const result = await renderWithProviders(
    <SelectionBar
      selectedCount={2}
      pageSize={30}
      allOnPageSelected={false}
      {...spies}
      {...props}
    />,
  )
  return { spies, ...result }
}

describe('SelectionBar', () => {
  it('nie renderuje się bez zaznaczenia', async () => {
    await renderBar({ selectedCount: 0 })
    expect(screen.queryByTestId('chunks-selection-bar')).not.toBeInTheDocument()
  })

  it('pokazuje liczbę zaznaczonych chunków', async () => {
    await renderBar({ selectedCount: 3 })
    expect(screen.getByTestId('chunks-selection-bar')).toHaveTextContent('Zaznaczono 3')
  })

  it('każdy przycisk woła swój callback', async () => {
    const { spies } = await renderBar()
    const user = userEvent.setup()

    await user.click(screen.getByTestId('chunks-select-page'))
    await user.click(screen.getByTestId('chunks-bulk-enable'))
    await user.click(screen.getByTestId('chunks-bulk-disable'))
    await user.click(screen.getByTestId('chunks-bulk-delete'))

    expect(spies.onTogglePage).toHaveBeenCalledTimes(1)
    expect(spies.onEnable).toHaveBeenCalledTimes(1)
    expect(spies.onDisable).toHaveBeenCalledTimes(1)
    expect(spies.onDelete).toHaveBeenCalledTimes(1)
  })

  it('przy całej zaznaczonej stronie etykieta to „Odznacz stronę”', async () => {
    await renderBar({ allOnPageSelected: true })
    expect(screen.getByTestId('chunks-select-page')).toHaveTextContent('Odznacz stronę')
  })

  it('bez chunków na stronie nie ma czego zaznaczać', async () => {
    await renderBar({ pageSize: 0 })
    expect(screen.getByTestId('chunks-select-page')).toBeDisabled()
  })
})
