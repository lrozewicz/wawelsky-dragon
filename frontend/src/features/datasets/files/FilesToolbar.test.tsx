/**
 * Pasek narzędzi zakładki Pliki (kontrakt WP E3-3b §T5): debounce wyszukiwania 400 ms, filtry
 * „Typ pliku”/„Status” (oba wracają na stronę 1) i przycisk „Prześlij plik”.
 */

import { useState } from 'react'
import type { JSX } from 'react'
import { act, cleanup, fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { FilesToolbar, SEARCH_DEBOUNCE_MS } from './FilesToolbar'
import { DEFAULT_DOCUMENTS_QUERY } from './queries'
import type { DocumentsQuery } from './queries'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

/** Stan trzyma harness — pasek jest komponentem kontrolowanym przez rodzica. */
function Harness(props: {
  onChange: (query: DocumentsQuery) => void
  onAdd?: () => void
}): JSX.Element {
  const [query, setQuery] = useState<DocumentsQuery>(DEFAULT_DOCUMENTS_QUERY)

  return (
    <FilesToolbar
      query={query}
      onChange={(next) => {
        props.onChange(next)
        setQuery(next)
      }}
      onAdd={props.onAdd ?? (() => undefined)}
    />
  )
}

describe('FilesToolbar', () => {
  it('wysyła keywords dopiero po 400 ms od ostatniej zmiany', async () => {
    const onChange = vi.fn()
    await renderWithProviders(<Harness onChange={onChange} />)
    // Fałszywy zegar włączamy po renderze: `initI18n` i router ładują się asynchronicznie,
    // a debounce i tak powstaje dopiero przy pierwszej zmianie tekstu.
    vi.useFakeTimers()

    const input = within(screen.getByTestId('files-search')).getByRole('textbox')
    fireEvent.change(input, { target: { value: 'abc' } })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS - 1)
    })
    expect(onChange).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0]?.[0]).toMatchObject({ keywords: 'abc', page: 1 })
  })

  it('kolejne znaki przesuwają termin — żądanie idzie z ostatnią wartością', async () => {
    const onChange = vi.fn()
    await renderWithProviders(<Harness onChange={onChange} />)
    vi.useFakeTimers()

    const input = within(screen.getByTestId('files-search')).getByRole('textbox')
    fireEvent.change(input, { target: { value: 'ab' } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS - 100)
    })
    fireEvent.change(input, { target: { value: 'abc' } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
    })

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0]?.[0]).toMatchObject({ keywords: 'abc', page: 1 })
  })

  it('filtr „Typ pliku” ustawia suffix i wraca na stronę 1', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    await renderWithProviders(<Harness onChange={onChange} />)

    await user.click(within(screen.getByTestId('files-filter-type')).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'pdf' }))

    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_DOCUMENTS_QUERY, suffix: ['pdf'], page: 1 })
  })

  it('filtr „Status” wysyła kod run i wraca na stronę 1', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    await renderWithProviders(<Harness onChange={onChange} />)

    await user.click(within(screen.getByTestId('files-filter-status')).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'Sukces' }))

    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_DOCUMENTS_QUERY, run: ['3'], page: 1 })
  })

  it('„Wszystkie” w filtrze statusu czyści filtr', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()

    function PresetHarness(): JSX.Element {
      const [query, setQuery] = useState<DocumentsQuery>({
        ...DEFAULT_DOCUMENTS_QUERY,
        run: ['3'],
      })
      return (
        <FilesToolbar
          query={query}
          onChange={(next) => {
            onChange(next)
            setQuery(next)
          }}
          onAdd={() => undefined}
        />
      )
    }

    await renderWithProviders(<PresetHarness />)

    await user.click(within(screen.getByTestId('files-filter-status')).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'Wszystkie' }))

    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_DOCUMENTS_QUERY, run: [], page: 1 })
  })

  it('„Prześlij plik” woła onAdd', async () => {
    const onAdd = vi.fn()
    const user = userEvent.setup()
    await renderWithProviders(<Harness onChange={vi.fn()} onAdd={onAdd} />)

    await user.click(screen.getByTestId('files-add'))

    expect(onAdd).toHaveBeenCalledTimes(1)
  })

  it('showAdd=false chowa „Prześlij plik” (pusty wynik filtra metadanych — kontrakt WP E6-1b §4)', async () => {
    await renderWithProviders(
      <FilesToolbar
        query={DEFAULT_DOCUMENTS_QUERY}
        onChange={() => undefined}
        onAdd={() => undefined}
        showAdd={false}
      />,
    )

    expect(screen.queryByTestId('files-add')).not.toBeInTheDocument()
    expect(screen.getByTestId('files-search')).toBeInTheDocument()
  })
})
