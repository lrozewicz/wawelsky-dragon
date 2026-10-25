/**
 * Testy `ChunkMethodDialog` (kontrakt WP E3-3b §T6, rozbudowa WP E5-H8c §3): lista metod pochodzi
 * z `CHUNK_METHODS`, wartość startowa to konfiguracja DOKUMENTU (metoda, parser PDF, zakres stron),
 * nad polem jest ostrzeżenie o ponownym parsowaniu, a zapis oddaje metodę i scalony `parser_config`.
 */

import { useState } from 'react'
import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fixtureModel, modelsHandlers } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { ChunkMethodDialog } from './ChunkMethodDialog'
import type { ChunkMethod } from '../queries'

afterEach(cleanup)

function Harness({
  onSave,
  method = 'naive',
  parserConfig = {},
}: {
  onSave: (method: ChunkMethod, parserConfig: Record<string, unknown>) => void
  method?: string
  parserConfig?: Record<string, unknown>
}) {
  const [open, setOpen] = useState(true)
  return (
    <>
      {/* MUI oznacza treść poza oknem jako `aria-hidden`, więc przełącznik znajdujemy po testid. */}
      <button type="button" data-testid="toggle" onClick={() => setOpen((value) => !value)}>
        toggle
      </button>
      <ChunkMethodDialog
        open={open}
        method={method}
        parserConfig={parserConfig}
        onSave={onSave}
        onClose={() => setOpen(false)}
      />
    </>
  )
}

function select(testid: string): HTMLElement {
  return within(screen.getByTestId(testid)).getByRole('combobox')
}

beforeEach(() => {
  // Model wizji dla selecta parsera (jak w konfiguracji datasetu, E5-H8c §3).
  server.use(...modelsHandlers([fixtureModel({ name: 'fake-vision', model_type: ['vision'] })]))
})

describe('ChunkMethodDialog', () => {
  it('pokazuje ostrzeżenie i metodę dokumentu', async () => {
    await renderWithProviders(<Harness onSave={vi.fn()} method="table" />)

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Zmiana metody wymaga ponownego sparsowania dokumentu.',
    )
    expect(select('method-select')).toHaveTextContent('Table')
  })

  it('nieznana metoda spada na pierwszą z listy', async () => {
    await renderWithProviders(<Harness onSave={vi.fn()} method="nieznana" />)
    expect(select('method-select')).toHaveTextContent('General')
  })

  it('pokazuje faktyczną konfigurację pliku: parser i zakres stron', async () => {
    await renderWithProviders(
      <Harness
        onSave={vi.fn()}
        parserConfig={{ layout_recognize: 'fake-vision', pages: [[2, 3]], chunk_token_num: 512 }}
      />,
    )

    expect(select('doc-pdf-parser-select')).toHaveTextContent('fake-vision')
    expect(screen.getByTestId('pages-from-0')).toHaveValue(2)
    expect(screen.getByTestId('pages-to-0')).toHaveValue(3)
  })

  it('brak parsera w konfiguracji pokazuje domyślny DeepDOC i pusty zakres', async () => {
    await renderWithProviders(<Harness onSave={vi.fn()} />)

    expect(select('doc-pdf-parser-select')).toHaveTextContent('Auto')
    expect(screen.queryByTestId('pages-from-0')).toBeNull()
  })

  it('zmiana metody oddaje ją w `onSave` razem ze scalonym parser_config', async () => {
    const onSave = vi.fn()
    await renderWithProviders(
      <Harness onSave={onSave} parserConfig={{ chunk_token_num: 512, pages: [[2, 3]] }} />,
    )
    const user = userEvent.setup()

    await user.click(select('method-select'))
    await user.click(await screen.findByRole('option', { name: 'Q&A' }))
    await user.click(screen.getByTestId('method-save'))

    expect(onSave).toHaveBeenCalledWith('qa', {
      chunk_token_num: 512,
      layout_recognize: 'DeepDOC',
      pages: [[2, 3]],
    })
  })

  it('zapis oddaje zmieniony parser i zakres, nie ruszając pozostałych kluczy', async () => {
    const onSave = vi.fn()
    await renderWithProviders(
      <Harness
        onSave={onSave}
        parserConfig={{ chunk_token_num: 512, layout_recognize: 'fake-vision', pages: [[2, 3]] }}
      />,
    )
    const user = userEvent.setup()

    await user.click(select('doc-pdf-parser-select'))
    await user.click(await screen.findByRole('option', { name: 'Tylko tekst' }))
    await user.clear(screen.getByTestId('pages-from-0'))
    await user.type(screen.getByTestId('pages-from-0'), '1')
    await user.clear(screen.getByTestId('pages-to-0'))
    await user.type(screen.getByTestId('pages-to-0'), '3')
    await user.click(screen.getByTestId('method-save'))

    expect(onSave).toHaveBeenCalledWith('naive', {
      chunk_token_num: 512,
      layout_recognize: 'Plain Text',
      pages: [[1, 3]],
    })
  })

  it('niewypełniony wiersz zakresu pomija przy zapisie (SC-E5-H9-05, bez ukrytego „1-1”)', async () => {
    const onSave = vi.fn()
    await renderWithProviders(<Harness onSave={onSave} parserConfig={{ chunk_token_num: 512 }} />)
    const user = userEvent.setup()

    // „Dodaj zakres” wstawia pusty wiersz; zapis bez wypełniania nie niesie `null` do backendu.
    await user.click(screen.getByTestId('pages-add'))
    expect(screen.getByTestId('pages-from-0')).toHaveValue(null)
    await user.click(screen.getByTestId('method-save'))

    expect(onSave).toHaveBeenCalledWith('naive', {
      chunk_token_num: 512,
      layout_recognize: 'DeepDOC',
      pages: [],
    })
  })

  it('półpełny wiersz zakresu blokuje zapis z komunikatem', async () => {
    const onSave = vi.fn()
    await renderWithProviders(<Harness onSave={onSave} parserConfig={{ chunk_token_num: 512 }} />)
    const user = userEvent.setup()

    await user.click(screen.getByTestId('pages-add'))
    await user.type(screen.getByTestId('pages-from-0'), '2')

    // Zapis zablokowany (`pointer-events: none` wyklucza klik), komunikat pod edytorem.
    expect(screen.getByTestId('method-save')).toBeDisabled()
    expect(screen.getByText('Uzupełnij oba pola zakresu albo usuń wiersz.')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('po ponownym otwarciu wraca do konfiguracji dokumentu', async () => {
    await renderWithProviders(
      <Harness
        onSave={vi.fn()}
        parserConfig={{ layout_recognize: 'fake-vision', pages: [[2, 3]] }}
      />,
    )
    const user = userEvent.setup()

    await user.click(select('method-select'))
    await user.click(await screen.findByRole('option', { name: 'Q&A' }))
    expect(select('method-select')).toHaveTextContent('Q&A')
    await user.clear(screen.getByTestId('pages-from-0'))
    await user.type(screen.getByTestId('pages-from-0'), '1')

    await user.click(screen.getByTestId('toggle'))
    await user.click(screen.getByTestId('toggle'))

    expect(select('method-select')).toHaveTextContent('General')
    expect(select('doc-pdf-parser-select')).toHaveTextContent('fake-vision')
    expect(screen.getByTestId('pages-from-0')).toHaveValue(2)
  })
})
