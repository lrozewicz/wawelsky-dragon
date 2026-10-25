import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { ChipListInput } from './ChipListInput'

afterEach(cleanup)

describe('ChipListInput', () => {
  it('Enter dodaje chip (trim, puste pomijane) i czyści pole', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const { rerender } = await renderWithProviders(
      <ChipListInput
        value={[]}
        onChange={onChange}
        inputLabel="Wartość"
        removeLabel={(v) => `Usuń wartość ${v}`}
      />,
    )

    const input = screen.getByLabelText('Wartość')
    await user.type(input, '  rok ')
    await user.keyboard('{Enter}')

    expect(onChange).toHaveBeenLastCalledWith(['rok'])
    // Stan kontrolowany — rerender z nową listą czyści pole wpisu.
    rerender(
      <ChipListInput
        value={['rok']}
        onChange={onChange}
        inputLabel="Wartość"
        removeLabel={(v) => `Usuń wartość ${v}`}
      />,
    )
    expect(screen.getByLabelText('Wartość')).toHaveValue('')
  })

  it('duplikat istniejącego chipa nie jest dodawany', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderWithProviders(
      <ChipListInput
        value={['rok', 'a']}
        onChange={onChange}
        inputLabel="Wartość"
        removeLabel={(v) => `Usuń wartość ${v}`}
      />,
    )

    await user.type(screen.getByLabelText('Wartość'), 'rok')
    await user.keyboard('{Enter}')

    // Wpis istniejącego chipa (trim) nie tworzy drugiego chipa o tej samej treści.
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getAllByText('rok')).toHaveLength(1)
  })

  it('Backspace na pustym polie nie usuwa chipa; × usuwa', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderWithProviders(
      <ChipListInput
        value={['a', 'b']}
        onChange={onChange}
        inputLabel="Wartość"
        removeLabel={(v) => `Usuń wartość ${v}`}
      />,
    )

    const input = screen.getByLabelText('Wartość')
    await user.click(input)
    await user.keyboard('{Backspace}')

    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByText('a')).toBeInTheDocument()
    expect(screen.getByText('b')).toBeInTheDocument()

    await user.click(screen.getByLabelText('Usuń wartość b'))
    expect(onChange).toHaveBeenLastCalledWith(['a'])
  })

  it('z podpowiedziami działa jak combobox: klik opcji dodaje chip', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    await renderWithProviders(
      <ChipListInput
        value={[]}
        onChange={onChange}
        inputLabel="Dodaj klucz"
        removeLabel={(v) => `Usuń klucz ${v}`}
        options={['rok', 'typ']}
      />,
    )

    await user.click(screen.getByLabelText('Dodaj klucz'))
    await user.click(await screen.findByRole('option', { name: 'typ' }))

    expect(onChange).toHaveBeenLastCalledWith(['typ'])
  })

  it('po dodaniu chipa nie ma clear indicatora ani pustego popupa przy fokusie (QA E6-1b-1 D1)', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const { container, rerender } = await renderWithProviders(
      <ChipListInput
        value={[]}
        onChange={onChange}
        inputLabel="Wartość"
        removeLabel={(v) => `Usuń wartość ${v}`}
      />,
    )

    const input = screen.getByLabelText('Wartość')
    await user.type(input, 'rok')
    await user.keyboard('{Enter}')
    rerender(
      <ChipListInput
        value={['rok']}
        onChange={onChange}
        inputLabel="Wartość"
        removeLabel={(v) => `Usuń wartość ${v}`}
      />,
    )

    // Defekt QA E6-1b-1 (MAJOR): pływający przycisk „×” (clear indicator Autocomplete) wewnątrz
    // kontenera chipów — chipy mają własne ×, clear indicator jest zbędnym duplikatem.
    expect(container.querySelector('.MuiAutocomplete-clearIndicator')).toBeNull()

    // Pusty panel podpowiedzi przy fokusie (freeSolo bez opcji) — popup nie może się otworzyć.
    await user.click(input)
    expect(document.querySelector('.MuiAutocomplete-popper')).toBeNull()

    // × na samych chipach zostaje (kontrakt §4: usuwanie tylko przez × z aria-label).
    expect(screen.getByRole('button', { name: 'Usuń wartość rok' })).toBeInTheDocument()
  })

  it('x chipa dostaje aria-label z wartością chipu', async () => {
    await renderWithProviders(
      <ChipListInput
        value={['raport']}
        onChange={vi.fn()}
        inputLabel="Wartość"
        removeLabel={(v) => `Usuń wartość ${v}`}
      />,
    )

    expect(screen.getByLabelText('Usuń wartość raport')).toBeInTheDocument()
    // × jest prawdziwym przyciskiem (defekt T3: aria-label na svg nie daje role="button",
    // a e2e klika `getByRole('button', { name: 'Usuń …' })`).
    expect(screen.getByRole('button', { name: 'Usuń wartość raport' })).toBeInTheDocument()
  })
})
