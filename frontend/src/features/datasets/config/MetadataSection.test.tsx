/**
 * Testy `MetadataSection` (kontrakt WP E6-1b §4): przełącznik zależny od listy pól, dodanie
 * wiersza z fokusem w „Klucz”, chipy dozwolonych wartości przez `ChipListInput`, komunikaty
 * walidacji klucza i usunięcie wiersza. Stan trzyma harness — komponent sam go nie pamięta.
 */
import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { useState } from 'react'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { MetadataSection } from './MetadataSection'
import type { MetaFieldDef } from '../../metadata/types'

afterEach(cleanup)

function Harness(props: {
  initial: MetaFieldDef[]
  errors?: Array<'ok' | 'required' | 'duplicate'>
  initialAuto?: boolean
  saveError?: string | null
}) {
  const [fields, setFields] = useState(props.initial)
  const [auto, setAuto] = useState(props.initialAuto ?? false)
  return (
    <MetadataSection
      fields={fields}
      errors={props.errors ?? fields.map(() => 'ok' as const)}
      autoEnabled={auto}
      onAutoChange={setAuto}
      onFieldsChange={setFields}
      saveError={props.saveError ?? null}
    />
  )
}

describe('MetadataSection', () => {
  it('przy pustej liście przełącznik jest nieaktywny z podpowiedzią', async () => {
    await renderWithProviders(<Harness initial={[]} />)

    expect(screen.getByRole('switch', { name: 'Auto-metadane' })).toBeDisabled()
    expect(screen.getByText('Dodaj co najmniej jedno pole')).toBeInTheDocument()
  })

  it('„+ Pole” dodaje wiersz z fokusem w „Klucz” i odblokowuje przełącznik', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<Harness initial={[]} />)

    await user.click(screen.getByRole('button', { name: '+ Pole' }))

    const row = screen.getByRole('group', { name: 'Pole 1' })
    expect(row).toBeInTheDocument()
    const key = within(row).getByLabelText('Klucz')
    expect(key).toHaveFocus()
    expect(screen.getByRole('switch', { name: 'Auto-metadane' })).toBeEnabled()
  })

  it('Enter w „Dozwolonej wartości” dodaje chip i czyści pole; opis przyjmuje tekst', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<Harness initial={[{ key: '', description: '', enum: [] }]} />)

    const row = screen.getByRole('group', { name: 'Pole 1' })
    await user.type(within(row).getByLabelText('Klucz'), 'typ')
    await user.type(within(row).getByLabelText('Opis'), 'Rodzaj dokumentu')
    const value = within(row).getByLabelText('Dozwolona wartość')
    await user.type(value, 'raport')
    await user.keyboard('{Enter}')

    expect(within(row).getByLabelText('Usuń wartość raport')).toBeInTheDocument()
    expect(value).toHaveValue('')
    expect(within(row).getByLabelText('Opis')).toHaveValue('Rodzaj dokumentu')
  })

  it('błędy klucza: „required” i „duplicate” pokazują komunikat i aria-invalid', async () => {
    await renderWithProviders(
      <Harness
        initial={[
          { key: 'rok', description: '', enum: [] },
          { key: 'rok', description: '', enum: [] },
        ]}
        errors={['ok', 'duplicate']}
      />,
    )

    const second = screen.getByRole('group', { name: 'Pole 2' })
    expect(within(second).getByText('Klucz musi być unikalny')).toBeInTheDocument()
    expect(within(second).getByLabelText('Klucz')).toHaveAttribute('aria-invalid', 'true')
  })

  it('„Klucz jest wymagany” pojawia się dopiero po opuszczeniu pola (SC-E67-z2-06)', async () => {
    const user = userEvent.setup()
    await renderWithProviders(
      <Harness initial={[{ key: '', description: '', enum: [] }]} errors={['required']} />,
    )

    const row = screen.getByRole('group', { name: 'Pole 1' })
    expect(within(row).queryByText('Klucz jest wymagany')).not.toBeInTheDocument()

    await user.click(within(row).getByLabelText('Klucz'))
    expect(within(row).queryByText('Klucz jest wymagany')).not.toBeInTheDocument()
    await user.click(within(row).getByLabelText('Opis'))

    expect(within(row).getByText('Klucz jest wymagany')).toBeInTheDocument()
  })

  it('pole „Klucz” niesie pełny klucz w title; < md pola mają widoczne etykiety (jsdom bez matchMedia)', async () => {
    await renderWithProviders(
      <Harness initial={[{ key: 'bardzo_dlugi_klucz_metadanych', description: '', enum: [] }]} />,
    )

    const row = screen.getByRole('group', { name: 'Pole 1' })
    expect(within(row).getByLabelText('Klucz')).toHaveAttribute(
      'title',
      'bardzo_dlugi_klucz_metadanych',
    )
    // Nagłówek kolumn schowany (< md) — etykieta pola jest jedyną.
    expect(row.querySelectorAll('label')).toHaveLength(3)
  })

  it('≥ md nagłówek kolumn jest jedyną etykietą, a puste „Dozwolone wartości” ma krótki placeholder (T8)', async () => {
    const original = window.matchMedia
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
    })) as unknown as typeof window.matchMedia
    try {
      await renderWithProviders(
        <Harness initial={[{ key: 'bardzo_dlugi_klucz_metadanych', description: '', enum: [] }]} />,
      )
      const row = screen.getByRole('group', { name: 'Pole 1' })
      expect(row.querySelectorAll('label')).toHaveLength(0)
      expect(within(row).getByLabelText('Dozwolona wartość')).toHaveAttribute(
        'placeholder',
        'Wartości',
      )
    } finally {
      window.matchMedia = original
    }
  })

  it('„Usuń pole” zdejmuje wiersz', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<Harness initial={[{ key: 'rok', description: '', enum: [] }]} />)

    await user.click(
      within(screen.getByRole('group', { name: 'Pole 1' })).getByRole('button', {
        name: 'Usuń pole',
      }),
    )

    expect(screen.queryByRole('group', { name: 'Pole 1' })).not.toBeInTheDocument()
  })

  it('przełącznik działa przy niepustej liście i ⓘ ma podpowiedź z aria-label', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<Harness initial={[{ key: 'rok', description: '', enum: [] }]} />)

    const autoSwitch = screen.getByRole('switch', { name: 'Auto-metadane' })
    await user.click(autoSwitch)
    expect(autoSwitch).toBeChecked()
    expect(screen.getByRole('button', { name: 'Informacja o auto-metadanych' })).toBeInTheDocument()
  })

  it('usunięcie ostatniego pola przy włączonych auto-metadanych wyłącza przełącznik (T4)', async () => {
    // Stan defektowy na bazie: `enable_metadata=true` z pustą listą pól (checked + disabled).
    const user = userEvent.setup()
    await renderWithProviders(
      <Harness initial={[{ key: 'rok', description: '', enum: [] }]} initialAuto />,
    )

    await user.click(
      within(screen.getByRole('group', { name: 'Pole 1' })).getByRole('button', {
        name: 'Usuń pole',
      }),
    )

    const autoSwitch = screen.getByRole('switch', { name: 'Auto-metadane' })
    expect(autoSwitch).not.toBeChecked()
    expect(autoSwitch).toBeDisabled()
  })

  it('błąd zapisu pól metadanych: komunikat przy sekcji pól, nie alert karty (T4, 08 §7.14 U5)', async () => {
    await renderWithProviders(
      <Harness
        initial={[{ key: 'rok', description: '', enum: [] }]}
        saveError="Nie udało się zapisać pól metadanych"
      />,
    )

    expect(screen.getByText('Nie udało się zapisać pól metadanych')).toBeInTheDocument()
  })

  it('błąd zapisu przy pustej liście pól (usunięto wszystkie) jest widoczny przy sekcji', async () => {
    await renderWithProviders(
      <Harness initial={[]} saveError="Nie udało się zapisać pól metadanych" />,
    )

    expect(screen.getByText('Nie udało się zapisać pól metadanych')).toBeInTheDocument()
  })
})
