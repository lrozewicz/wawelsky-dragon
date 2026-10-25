/**
 * Testy `ChunksToolbar` (kontrakt WP E3-4a §T3): wyszukiwanie leci po 400 ms od ostatniego znaku
 * (i tylko raz), przełącznik widoku mapuje się na `expanded`, filtr dostępności zwraca wartość
 * z `ToggleButtonGroup`, a „Nowy chunk” woła `onAdd`.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { act, cleanup, fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { CHUNKS_SEARCH_DEBOUNCE_MS, ChunksToolbar } from './ChunksToolbar'
import type { ChunksFilter } from './ChunksToolbar'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

/** Stan trzyma harness — pasek jest w całości kontrolowany przez rodzica. */
function Harness(props: {
  onKeywordsChange: (v: string) => void
  onExpandedChange?: (v: boolean) => void
  onFilterChange?: (f: ChunksFilter) => void
  onAdd?: () => void
}): JSX.Element {
  const [expanded, setExpanded] = useState(true)
  const [filter, setFilter] = useState<ChunksFilter>('all')

  return (
    <ChunksToolbar
      expanded={expanded}
      onExpandedChange={(next) => {
        props.onExpandedChange?.(next)
        setExpanded(next)
      }}
      filter={filter}
      onFilterChange={(next) => {
        props.onFilterChange?.(next)
        setFilter(next)
      }}
      keywords=""
      onKeywordsChange={props.onKeywordsChange}
      onAdd={props.onAdd ?? (() => undefined)}
    />
  )
}

describe('ChunksToolbar', () => {
  it('wysyła keywords dopiero po 400 ms od ostatniej zmiany', async () => {
    const onKeywordsChange = vi.fn()
    await renderWithProviders(<Harness onKeywordsChange={onKeywordsChange} />)
    // Fałszywy zegar włączamy po renderze — `initI18n` i router ładują się asynchronicznie,
    // a debounce powstaje dopiero przy pierwszej zmianie tekstu.
    vi.useFakeTimers()

    fireEvent.change(screen.getByTestId('chunks-search'), { target: { value: 'abc' } })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(CHUNKS_SEARCH_DEBOUNCE_MS - 1)
    })
    expect(onKeywordsChange).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(onKeywordsChange).toHaveBeenCalledTimes(1)
    expect(onKeywordsChange).toHaveBeenCalledWith('abc')
  })

  it('kolejne znaki przesuwają termin — żądanie idzie z ostatnią wartością', async () => {
    const onKeywordsChange = vi.fn()
    await renderWithProviders(<Harness onKeywordsChange={onKeywordsChange} />)
    vi.useFakeTimers()

    const input = screen.getByTestId('chunks-search')
    fireEvent.change(input, { target: { value: 'ab' } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CHUNKS_SEARCH_DEBOUNCE_MS - 100)
    })
    fireEvent.change(input, { target: { value: 'abc' } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CHUNKS_SEARCH_DEBOUNCE_MS)
    })

    expect(onKeywordsChange).toHaveBeenCalledTimes(1)
    expect(onKeywordsChange).toHaveBeenCalledWith('abc')
  })

  it('pole szukania ma placeholder z i18n', async () => {
    await renderWithProviders(<Harness onKeywordsChange={vi.fn()} />)
    expect(screen.getByTestId('chunks-search')).toHaveAttribute('placeholder', 'Szukaj w chunkach')
  })

  it('przełącznik widoku mapuje „Skrócony” na expanded=false', async () => {
    const onExpandedChange = vi.fn()
    await renderWithProviders(
      <Harness onKeywordsChange={vi.fn()} onExpandedChange={onExpandedChange} />,
    )

    await userEvent.setup().click(screen.getByRole('button', { name: 'Skrócony' }))

    expect(onExpandedChange).toHaveBeenCalledWith(false)
  })

  it('filtr dostępności zwraca wybraną wartość', async () => {
    const onFilterChange = vi.fn()
    await renderWithProviders(
      <Harness onKeywordsChange={vi.fn()} onFilterChange={onFilterChange} />,
    )

    await userEvent.setup().click(screen.getByTestId('chunks-filter-enabled'))

    expect(onFilterChange).toHaveBeenCalledWith('enabled')
  })

  it('„Nowy chunk” woła onAdd', async () => {
    const onAdd = vi.fn()
    await renderWithProviders(<Harness onKeywordsChange={vi.fn()} onAdd={onAdd} />)

    await userEvent.setup().click(screen.getByTestId('chunks-add'))

    expect(onAdd).toHaveBeenCalledTimes(1)
  })
})
