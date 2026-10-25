import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { MANUAL_FILTER, renderBuilder, useSummary } from '../../test/metadataBuilder'

import { EMPTY_META_FILTER } from './types'
import type { MetaFilter } from './types'

afterEach(cleanup)

describe('MetadataConditionBuilder — komunikat przy polu klucza (T6 c)', () => {
  it('warunek bez klucza: `keyError` jako helperText przy polu „Klucz” (aria-invalid)', async () => {
    await renderBuilder(
      { method: 'manual', logic: 'and', manual: [{ key: '', op: '=', value: '' }], semi_auto: [] },
      { keyError: 'Klucz warunku jest wymagany' },
    )

    const row = screen.getByRole('group', { name: 'Warunek 1' })
    expect(within(row).getByText('Klucz warunku jest wymagany')).toBeInTheDocument()
    expect(within(row).getByLabelText('Klucz')).toHaveAttribute('aria-invalid', 'true')
  })

  it('warunek z kluczem: `keyError` nie wyświetla się', async () => {
    await renderBuilder(MANUAL_FILTER, { keyError: 'Klucz warunku jest wymagany' })

    expect(screen.queryByText('Klucz warunku jest wymagany')).not.toBeInTheDocument()
  })
})

describe('MetadataConditionBuilder — auto i półautomatyczny', () => {
  it('auto: tylko podpowiedź, bez edytora', async () => {
    useSummary({ rok: { type: 'string', values: [['2023', 1]] } })
    const { onChange } = await renderBuilder({ ...MANUAL_FILTER, method: 'auto', manual: [] })

    expect(screen.getByText(/Model sam ułoży filtr z pytania/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Logika warunków')).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('półautomatyczny: etykieta, combobox „Dodaj klucz", chipy z „Usuń klucz <k>"', async () => {
    useSummary({ rok: { type: 'string', values: [['2023', 1]] } })
    const semiFilter: MetaFilter = { ...EMPTY_META_FILTER, method: 'semi_auto', semi_auto: ['rok'] }
    const { onChange } = await renderBuilder(semiFilter)

    expect(screen.getByText('Klucze, po których model może filtrować')).toBeInTheDocument()
    expect(screen.getByLabelText('Dodaj klucz')).toHaveRole('combobox')
    expect(screen.getByLabelText('Usuń klucz rok')).toBeInTheDocument()

    await userEvent.setup().click(screen.getByLabelText('Usuń klucz rok'))
    expect(onChange).toHaveBeenLastCalledWith({ ...semiFilter, semi_auto: [] })
  })

  it('półautomatyczny: „Dodaj klucz" podpowiada znane klucze', async () => {
    useSummary({
      rok: { type: 'string', values: [['2023', 1]] },
      typ: { type: 'string', values: [['raport', 1]] },
    })
    const semiFilter: MetaFilter = { ...EMPTY_META_FILTER, method: 'semi_auto', semi_auto: [] }
    const { onChange } = await renderBuilder(semiFilter)

    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Dodaj klucz'))
    await user.click(await screen.findByRole('option', { name: 'typ' }))
    expect(onChange).toHaveBeenLastCalledWith({ ...semiFilter, semi_auto: ['typ'] })
    expect(screen.getByText('typ')).toBeInTheDocument()
  })
})

describe('MetadataConditionBuilder — stan braku metadanych', () => {
  it('bazy bez metadanych i tryb ≠ off: komunikat z linkiem do konfiguracji datasetu', async () => {
    useSummary({})
    const { onChange } = await renderBuilder(MANUAL_FILTER, { datasetConfigLinkId: 'ds-1' })

    expect(await screen.findByText(/Bazy nie mają metadanych/)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Konfiguracji datasetu' })
    expect(link).toHaveAttribute('href', '/dataset/configuration/ds-1')
    // Edytor zastąpiony komunikatem — kontrolki filtrowania nie są pokazywane.
    expect(screen.queryByLabelText('Logika warunków')).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('bazy bez metadanych bez linku (brak datasetConfigLinkId): sam komunikat', async () => {
    useSummary({})
    await renderBuilder(MANUAL_FILTER)

    // Zdanie dokończone (nie urwane na „w”, T8 / SC-E67-z2-25).
    expect(
      await screen.findByText(
        'Bazy nie mają metadanych — zdefiniuj pola w Konfiguracji bazy wiedzy.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('bazy z metadanymi: komunikatu brak', async () => {
    useSummary({ typ: { type: 'string', values: [['raport', 1]] } })
    await renderBuilder(MANUAL_FILTER, { datasetConfigLinkId: 'ds-1' })

    // Załadowanie podsumowania widoczne jako select wartości (≤ 20 znanych) zamiast pola tekstowego.
    await screen.findByRole('combobox', { name: 'Wartość' })
    expect(screen.queryByText(/Bazy nie mają metadanych/)).not.toBeInTheDocument()
  })
})

describe('MetadataConditionBuilder — wyłączenie (disabled)', () => {
  it('disabled wyłącza kontrolki warunków i przełącznik', async () => {
    useSummary({ typ: { type: 'string', values: [['raport', 1]] } })
    const { onChange } = await renderBuilder(MANUAL_FILTER, { disabled: true })

    expect(screen.getByLabelText('Klucz')).toBeDisabled()
    // Select MUI: disabled jako aria-disabled na divie comboboxa.
    expect(screen.getByLabelText('Operator')).toHaveAttribute('aria-disabled', 'true')
    // Combobox wartości (Autocomplete) deaktywuje wejście standardowo.
    expect(await screen.findByRole('combobox', { name: 'Wartość' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '+ Warunek' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Usuń warunek' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'Ręczny' })).toBeDisabled()
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('MetadataConditionBuilder — próg 20 znanych wartości (CONTRACT §4)', () => {
  /** Podsumowanie z kluczem `rok` o podanej liczbie znanych wartości. */
  function useKnownValues(count: number): void {
    useSummary({
      rok: {
        type: 'string',
        values: Array.from({ length: count }, (_, i) => [`v${i + 1}`, 1] as [string, number]),
      },
    })
  }

  it('20 znanych wartości: wartość jako select (granica włącznie)', async () => {
    useKnownValues(20)
    await renderBuilder({ ...MANUAL_FILTER, manual: [{ key: 'rok', op: '=', value: '' }] })

    expect(await screen.findByRole('combobox', { name: 'Wartość' })).toBeInTheDocument()
  })

  it('21 znanych wartości: wartość polem tekstowym', async () => {
    useKnownValues(21)
    await renderBuilder({ ...MANUAL_FILTER, manual: [{ key: 'rok', op: '=', value: '' }] })

    // Marker załadowania podsumowania: podpowiedzi klucza w comboboxie.
    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Klucz'))
    await screen.findByRole('option', { name: 'rok' })
    await user.keyboard('{Escape}')

    expect(screen.getByRole('textbox', { name: 'Wartość' })).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Wartość' })).not.toBeInTheDocument()
  })
})

describe('MetadataConditionBuilder — podpowiedź ⓘ przy empty/not empty (QA E6-1b-2 A)', () => {
  // Podsumowanie z kluczem `typ`: bez tego atrapa domyślna zwraca bazy bez metadanych
  // (hasAny=false), a wiersz warunku znika po załadowaniu podsumowania.
  const TYP_SUMMARY = { typ: { type: 'string', values: [['raport', 1] as [string, number]] } }

  it('empty: podpowiedź przy operatorze, bez edytora wartości', async () => {
    useSummary(TYP_SUMMARY)
    await renderBuilder({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'empty', value: '' }],
    })

    const row = screen.getByRole('group', { name: 'Warunek 1' })
    expect(
      within(row).getByRole('img', { name: 'Dotyczy tylko dokumentów, które mają to pole' }),
    ).toBeInTheDocument()
    expect(within(row).queryByLabelText('Wartość')).not.toBeInTheDocument()
  })

  it('not empty: ta sama podpowiedź', async () => {
    useSummary(TYP_SUMMARY)
    await renderBuilder({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'not empty', value: '' }],
    })

    const row = screen.getByRole('group', { name: 'Warunek 1' })
    expect(
      within(row).getByRole('img', { name: 'Dotyczy tylko dokumentów, które mają to pole' }),
    ).toBeInTheDocument()
  })

  it('operator z wartością (`=`): podpowiedzi brak', async () => {
    useSummary(TYP_SUMMARY)
    await renderBuilder(MANUAL_FILTER)

    const row = screen.getByRole('group', { name: 'Warunek 1' })
    expect(
      within(row).queryByRole('img', { name: 'Dotyczy tylko dokumentów, które mają to pole' }),
    ).not.toBeInTheDocument()
  })
})
