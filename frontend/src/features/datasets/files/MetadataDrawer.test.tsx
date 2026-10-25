/**
 * Testy `MetadataDrawer` (kontrakt WP E6-1b §4, SC-E6-1b-03): szuflada z tytułem = nazwa pliku,
 * stan pusty z „+ Pole” (fokus w „Klucz”), zapis przez `patchDocumentMeta` z wartościami
 * nietkniętymi zachowującymi typ (T2), wartość-lista jako edytor chipów, błąd zapisu w alercie
 * z wartościami, które zostają, oraz „Anuluj” bez zapisu.
 */

import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import { MetadataDrawer } from './MetadataDrawer'

const patchDocumentMeta = vi.hoisted(() => vi.fn())

vi.mock('../../metadata/queries', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../metadata/queries')>()
  return { ...actual, patchDocumentMeta }
})

afterEach(() => {
  cleanup()
  patchDocumentMeta.mockReset()
})

type DrawerDoc = { id: string; name: string; meta_fields: Record<string, unknown> }

function doc(overrides: Partial<DrawerDoc> = {}): DrawerDoc {
  return { id: 'doc-1', name: 'raport.pdf', meta_fields: {}, ...overrides }
}

function renderDrawer(props: {
  doc?: DrawerDoc | null
  open?: boolean
  onClose?: () => void
  datasetId?: string
}) {
  const onClose = props.onClose ?? vi.fn()
  const view = renderWithProviders(
    <MetadataDrawer
      open={props.open ?? true}
      datasetId={props.datasetId ?? 'ds-1'}
      doc={props.doc === undefined ? doc() : props.doc}
      onClose={onClose}
    />,
  )
  return { onClose, ...view }
}

describe('MetadataDrawer', () => {
  it('duplikat klucza: komunikat przy polu klucza powtórzonego wiersza (T5a/T3 MINOR)', async () => {
    const user = userEvent.setup()
    await renderDrawer({})

    const dialog = await screen.findByRole('dialog', { name: 'raport.pdf' })
    await user.click(within(dialog).getByRole('button', { name: '+ Pole' }))
    await user.type(within(dialog).getByLabelText('Klucz'), 'typ')
    await user.click(within(dialog).getByRole('button', { name: '+ Pole' }))
    await user.type(within(dialog).getAllByLabelText('Klucz')[1]!, 'typ')
    expect(within(dialog).getAllByText(/Klucz musi być unikalny/).length).toBeGreaterThan(0)
  })
  it('szuflada z tytułem = nazwa pliku; stan pusty pokazuje tekst i „+ Pole”', async () => {
    await renderDrawer({ doc: doc({ name: 'duża nazwa pliku.pdf', meta_fields: {} }) })

    const dialog = await screen.findByRole('dialog', { name: 'duża nazwa pliku.pdf' })
    expect(within(dialog).getByText('Brak metadanych — dodaj pierwsze pole')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '+ Pole' })).toBeEnabled()
    // SC-V13-11: bez zmian „Zapisz” jest nieaktywny z powodem pod przyciskiem.
    const save = within(dialog).getByRole('button', { name: 'Zapisz' })
    expect(save).toBeDisabled()
    expect(save).toHaveAttribute('aria-describedby', 'metadata-save-reason')
    expect(within(dialog).getByText('Brak zmian do zapisania')).toBeInTheDocument()
  })

  it('„+ Pole” dodaje wiersz i przenosi fokus do „Klucz”', async () => {
    const user = userEvent.setup()
    await renderDrawer({})

    await user.click(await screen.findByRole('button', { name: '+ Pole' }))
    const key = screen.getByLabelText('Klucz')
    expect(key).toHaveFocus()
    expect(screen.queryByText('Brak metadanych — dodaj pierwsze pole')).not.toBeInTheDocument()
  })

  it('„Zapisz” wysyła cały słownik `meta_fields` i zamyka szufladę z toastem', async () => {
    patchDocumentMeta.mockResolvedValue(undefined)
    const user = userEvent.setup()
    const onClose = vi.fn()
    await renderDrawer({ onClose })

    await user.click(await screen.findByRole('button', { name: '+ Pole' }))
    await user.type(screen.getByLabelText('Klucz'), 'typ')
    await user.type(screen.getByLabelText('Wartość'), 'raport')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() =>
      expect(patchDocumentMeta).toHaveBeenCalledWith('ds-1', 'doc-1', { typ: 'raport' }),
    )
    expect(await screen.findByText('Zapisano metadane')).toBeInTheDocument()
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })

  it('wartość nietknięta zachowuje typ (liczba 2023 nie idzie jako tekst)', async () => {
    patchDocumentMeta.mockResolvedValue(undefined)
    const user = userEvent.setup()
    await renderDrawer({ doc: doc({ meta_fields: { rok: 2023, typ: 'raport' } }) })

    // Zmiana innego pola aktywuje „Zapisz” (SC-V13-11); nietknięta liczba zostaje liczbą (T2).
    // Dwa wiersze → drugie pole „Wartość” należy do wiersza „typ”.
    const value = (await screen.findAllByLabelText('Wartość'))[1]!
    await user.clear(value)
    await user.type(value, 'nowa')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() =>
      expect(patchDocumentMeta).toHaveBeenCalledWith('ds-1', 'doc-1', {
        rok: 2023,
        typ: 'nowa',
      }),
    )
  })

  it('wartość-lista edytuje się edytorem chipów i zapisuje jako tablica', async () => {
    patchDocumentMeta.mockResolvedValue(undefined)
    const user = userEvent.setup()
    await renderDrawer({ doc: doc({ meta_fields: { tagi: ['a', 'b'] } }) })

    expect(await screen.findByText('a')).toBeInTheDocument()
    expect(screen.getByText('b')).toBeInTheDocument()
    // Dodanie pola aktywuje „Zapisz” (SC-V13-11); chipy nietknięte idą dalej jako tablica.
    // Dwa wiersze → nowe pole to drugie „Klucz”/„Wartość”.
    await user.click(screen.getByRole('button', { name: '+ Pole' }))
    await user.type((await screen.findAllByLabelText('Klucz'))[1]!, 'nowy')
    await user.type((await screen.findAllByLabelText('Wartość'))[1]!, 'x')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() =>
      expect(patchDocumentMeta).toHaveBeenCalledWith('ds-1', 'doc-1', {
        tagi: ['a', 'b'],
        nowy: 'x',
      }),
    )
  })

  it('błąd zapisu pokazuje alert, wartości zostają, szuflada się nie zamyka', async () => {
    patchDocumentMeta.mockRejectedValue(new Error('boom'))
    const user = userEvent.setup()
    const onClose = vi.fn()
    await renderDrawer({ doc: doc({ meta_fields: { typ: 'raport' } }), onClose })

    const value = await screen.findByLabelText('Wartość')
    await user.clear(value)
    await user.type(value, 'nowa')
    await user.click(screen.getByRole('button', { name: 'Zapisz' }))

    expect(await screen.findByText('Nie udało się zapisać metadanych')).toBeInTheDocument()
    expect(screen.getByLabelText('Wartość')).toHaveValue('nowa')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('„Anuluj” zamyka szufladę bez wywołania zapisu', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    await renderDrawer({ doc: doc({ meta_fields: { typ: 'raport' } }), onClose })

    await user.click(await screen.findByRole('button', { name: 'Anuluj' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(patchDocumentMeta).not.toHaveBeenCalled()
  })

  it('„Anuluj” przy zmianach pyta „Odrzucić zmiany?”; „Odrzuć” zamyka bez zapisu (SC-V12-07)', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    await renderDrawer({ doc: doc({ meta_fields: { typ: 'raport' } }), onClose })

    const value = await screen.findByLabelText('Wartość')
    await user.clear(value)
    await user.type(value, 'nowa')
    await user.click(screen.getByRole('button', { name: 'Anuluj' }))

    expect(await screen.findByText('Odrzucić zmiany?')).toBeInTheDocument()
    expect(
      screen.getByText('Niezapisane zmiany w metadanych pliku zostaną utracone.'),
    ).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Odrzuć' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(patchDocumentMeta).not.toHaveBeenCalled()
  })
})
