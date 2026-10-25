import { useState } from 'react'
import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { SearchBar } from './SearchBar'
import type { SearchBarProps } from './SearchBar'

afterEach(cleanup)

// Napisy z `locales/pl/searches.json` — test chodzi na interfejsie polskim (domyślnym).
const LABEL = 'Pytanie'
const SUBMIT = 'Wyślij'
const PLACEHOLDER = 'Zadaj pytanie…'

async function renderBar(overrides: Partial<SearchBarProps> = {}) {
  const onSubmit = vi.fn()
  const result = await renderWithProviders(
    <SearchBar value="" onSubmit={onSubmit} {...overrides} />,
  )
  return { onSubmit, ...result }
}

/** Namiastka ekranu wyników: trzyma `value` w stanie, by dało się zmienić props z zewnątrz. */
function ValueHarness() {
  const [value, setValue] = useState('')
  return (
    <>
      <button type="button" onClick={() => setValue('z zewnątrz')}>
        {PLACEHOLDER}
      </button>
      <SearchBar value={value} onSubmit={() => {}} />
    </>
  )
}

describe('SearchBar', () => {
  it('pole ma etykietę i placeholder z i18n', async () => {
    await renderBar()

    expect(screen.getByLabelText(LABEL)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(PLACEHOLDER)).toBeInTheDocument()
  })

  it('wpisanie tekstu i Enter woła onSubmit z przyciętym tekstem', async () => {
    const { onSubmit } = await renderBar()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(LABEL), '  smok  {Enter}')

    expect(onSubmit).toHaveBeenCalledWith('smok')
  })

  it('przycisk wysyłki woła onSubmit', async () => {
    const { onSubmit } = await renderBar()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(LABEL), 'smok')
    await user.click(screen.getByRole('button', { name: SUBMIT }))

    expect(onSubmit).toHaveBeenCalledWith('smok')
  })

  it('pusty tekst nie woła onSubmit', async () => {
    const { onSubmit } = await renderBar()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(LABEL), '   {Enter}')
    await user.click(screen.getByRole('button', { name: SUBMIT }))

    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('zmiana propsa `value` podstawia nowy tekst do pola', async () => {
    await renderWithProviders(<ValueHarness />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(LABEL), 'szkic')
    expect(screen.getByLabelText(LABEL)).toHaveValue('szkic')

    await user.click(screen.getByRole('button', { name: PLACEHOLDER }))

    expect(screen.getByLabelText(LABEL)).toHaveValue('z zewnątrz')
  })

  it('`sticky` przykleja pasek do góry', async () => {
    await renderBar({ sticky: true })

    expect(screen.getByTestId('search-bar')).toHaveStyle({ position: 'sticky', top: '0px' })
  })

  it('bez `sticky` pasek nie jest przyklejony', async () => {
    await renderBar()

    expect(screen.getByTestId('search-bar')).not.toHaveStyle({ position: 'sticky' })
  })

  it('`large` wyśrodkowuje pole o ograniczonej szerokości', async () => {
    await renderBar({ large: true })

    expect(screen.getByTestId('search-bar')).toHaveStyle({ maxWidth: '720px' })
  })
})
