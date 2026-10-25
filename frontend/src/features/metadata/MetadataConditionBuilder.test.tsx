import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import {
  FIXTURE_SUMMARY,
  MANUAL_FILTER,
  chooseSelectOption,
  renderBuilder,
  useSummary,
} from '../../test/metadataBuilder'

import { EMPTY_META_FILTER } from './types'

afterEach(cleanup)

describe('MetadataConditionBuilder — przełącznik trybów', () => {
  it('pełna lista trybów: radiogroup z czterema radiami, klik przełącza metodę z pierwszym warunkiem', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder(EMPTY_META_FILTER)

    expect(screen.getByRole('radiogroup', { name: 'Tryb filtra metadanych' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Wyłączony' })).toBeChecked()

    // Przejście w „Ręczny” od razu daje pusty pierwszy warunek (SC-E6-1b-05 krok 2:
    // „Warunek 1” czeka zaraz po zaznaczeniu trybu) — z pierwszym znanym kluczem.
    await userEvent.setup().click(screen.getByRole('radio', { name: 'Ręczny' }))
    expect(onChange).toHaveBeenLastCalledWith({
      ...EMPTY_META_FILTER,
      method: 'manual',
      manual: [{ key: 'rok', op: '=', value: '' }],
    })
    expect(await screen.findByRole('group', { name: 'Warunek 1' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Ręczny' })).toBeChecked()
  })

  it('powrót do „Ręcznego” zachowuje istniejące warunki (bez dokładania drugiego)', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder(MANUAL_FILTER)

    await userEvent.setup().click(screen.getByRole('radio', { name: 'Automatyczny' }))
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      method: 'auto',
      manual: [{ key: 'typ', op: '=', value: 'raport' }],
    })
  })

  it('jeden tryb: bez przełącznika, od razu edytor warunków', async () => {
    useSummary(FIXTURE_SUMMARY)
    await renderBuilder(MANUAL_FILTER, { modes: ['manual'] })

    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Warunek 1' })).toBeInTheDocument()
  })

  it('tryby spoza listy `modes` są widoczne, ale nieaktywne (test retrievalu)', async () => {
    useSummary(FIXTURE_SUMMARY)
    await renderBuilder(EMPTY_META_FILTER, { modes: ['off', 'manual'] })

    expect(screen.getByRole('radio', { name: 'Wyłączony' })).toBeEnabled()
    expect(screen.getByRole('radio', { name: 'Ręczny' })).toBeEnabled()
    expect(screen.getByRole('radio', { name: 'Automatyczny' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'Półautomatyczny' })).toBeDisabled()
  })

  it('tryb off: sam przełącznik, bez edytora (bazy z metadanymi)', async () => {
    useSummary(FIXTURE_SUMMARY)
    await renderBuilder(EMPTY_META_FILTER)

    await waitFor(() =>
      expect(screen.queryByText(/Bazy nie mają metadanych/)).not.toBeInTheDocument(),
    )
    expect(screen.queryByLabelText('Logika warunków')).not.toBeInTheDocument()
  })

  it('tryb off i bazy bez metadanych: przełącznik plus komunikat (SC-E6-1b-05 krok 7)', async () => {
    useSummary({})
    const { onChange } = await renderBuilder(EMPTY_META_FILTER, {
      datasetConfigLinkId: 'ds-plain',
    })

    expect(await screen.findByText(/Bazy nie mają metadanych/)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Konfiguracji datasetu' })
    expect(link).toHaveAttribute('href', '/dataset/configuration/ds-plain')
    expect(screen.queryByLabelText('Logika warunków')).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('MetadataConditionBuilder — warunki ręczne', () => {
  it('wiersz warunku: klucz, operator, wartość jako combobox gdy op "=" i klucz ma ≤ 20 znanych wartości', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder(MANUAL_FILTER)

    const row = screen.getByRole('group', { name: 'Warunek 1' })
    expect(within(row).getByLabelText('Klucz')).toHaveValue('typ')
    expect(within(row).getByLabelText('Operator')).toHaveTextContent('=')
    // Combobox wartości z wolnym wpisem — bieżąca wartość żyje w inpucie (freeSolo MUI).
    expect(await within(row).findByRole('combobox', { name: 'Wartość' })).toHaveValue('raport')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('wartość nieobecna w dokumentach: wpis własny Enterem i wybór z podpowiedzi (SC-E6-1b-06 krok 2)', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder(MANUAL_FILTER)
    const user = userEvent.setup()

    const valueBox = await within(screen.getByRole('group', { name: 'Warunek 1' })).findByRole(
      'combobox',
      { name: 'Wartość' },
    )
    // Wpis własny poza listą znanych wartości („umowa”) zatwierdzany Enterem — ścisły Select
    // przyjmowałby tylko pozycje z listy (MINOR T1b).
    await user.clear(valueBox)
    await user.type(valueBox, 'umowa')
    await user.keyboard('{Enter}')
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: '=', value: 'umowa' }],
    })
    // Wartość znana — po wpisie zatwierdza się ta sama droga.
    await user.clear(valueBox)
    await user.type(valueBox, 'raport')
    await user.keyboard('{Enter}')
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: '=', value: 'raport' }],
    })
  })

  it('logika: „którykolwiek" zmienia logic na or', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder(MANUAL_FILTER)

    await chooseSelectOption('Logika warunków', 'którykolwiek')
    expect(onChange).toHaveBeenLastCalledWith({ ...MANUAL_FILTER, logic: 'or' })
  })

  it('operator bez wartości (empty/not empty): pole wartości znika, value jest ""', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder(MANUAL_FILTER)

    await chooseSelectOption('Operator', 'empty')
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'empty', value: '' }],
    })
    await waitFor(() => expect(screen.queryByLabelText('Wartość')).not.toBeInTheDocument())

    await chooseSelectOption('Operator', 'not empty')
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'not empty', value: '' }],
    })
  })

  it('zmiana operatora konwertuje wartość: "=" → "in" daje listę', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder(MANUAL_FILTER)

    await chooseSelectOption('Operator', 'in')
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'in', value: ['raport'] }],
    })
  })

  it('zmiana operatora konwertuje listę na tekst i "" dla empty', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'in', value: ['raport', 'ustawa'] }],
    })

    await chooseSelectOption('Operator', '=')
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: '=', value: 'raport, ustawa' }],
    })

    await chooseSelectOption('Operator', 'empty')
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'empty', value: '' }],
    })
  })

  it('warunki in/not in edytują wartość chipami: Enter dodaje, × usuwa', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'in', value: ['raport'] }],
    })

    const input = screen.getByLabelText('Wartość')
    const user = userEvent.setup()
    await user.type(input, 'ustawa')
    await user.keyboard('{Enter}')
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'in', value: ['raport', 'ustawa'] }],
    })
    expect(screen.getByText('ustawa')).toBeInTheDocument()

    await user.click(screen.getByLabelText('Usuń wartość raport'))
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'in', value: ['ustawa'] }],
    })
  })

  it('klucz: wybór z podpowiedzi comboboxa i wpis własny (kontrakt §4)', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder(MANUAL_FILTER)
    const user = userEvent.setup()

    // Wybór znanego klucza z podpowiedzi.
    await user.click(screen.getByLabelText('Klucz'))
    await user.click(await screen.findByRole('option', { name: 'rok' }))
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'rok', op: '=', value: 'raport' }],
    })

    // Wpis własny zatwierdzany Enterem.
    const input = screen.getByLabelText('Klucz')
    await user.clear(input)
    await user.type(input, 'region')
    await user.keyboard('{Enter}')
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'region', op: '=', value: 'raport' }],
    })
  })

  it('„+ Warunek" dodaje warunek z pierwszym znanym kluczem, "=" i wartością ""', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder(MANUAL_FILTER)

    await userEvent.setup().click(screen.getByRole('button', { name: '+ Warunek' }))
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [
        { key: 'typ', op: '=', value: 'raport' },
        { key: 'rok', op: '=', value: '' },
      ],
    })
    expect(screen.getByRole('group', { name: 'Warunek 2' })).toBeInTheDocument()
  })

  it('🗑 usuwa warunek', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder({
      ...MANUAL_FILTER,
      manual: [
        { key: 'typ', op: '=', value: 'raport' },
        { key: 'rok', op: '>', value: '2020' },
      ],
    })

    await userEvent
      .setup()
      .click(
        within(screen.getByRole('group', { name: 'Warunek 2' })).getByLabelText('Usuń warunek'),
      )
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: '=', value: 'raport' }],
    })
  })

  it('warunek bez klucza: pole klucza ma aria-invalid', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder({
      ...MANUAL_FILTER,
      manual: [{ key: '', op: '=', value: '' }],
    })

    expect(screen.getByLabelText('Klucz')).toHaveAttribute('aria-invalid', 'true')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('klucz bez znanych wartości lub op tekstowy: wartość polem tekstowym', async () => {
    useSummary({ rok: { type: 'string', values: [['2023', 1]] } })
    const { onChange } = await renderBuilder({
      ...MANUAL_FILTER,
      manual: [{ key: 'opis', op: 'contains', value: 'abc' }],
    })

    // Klucz „opis" nie występuje w podsumowaniu — wartość zostaje polem tekstowym.
    const valueField = screen.getByLabelText('Wartość')
    expect(valueField).toHaveValue('abc')
    await userEvent.setup().type(valueField, 'd')
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'opis', op: 'contains', value: 'abcd' }],
    })
  })
})
