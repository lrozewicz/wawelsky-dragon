/**
 * Defekt QA E6-1b-4 (T10): wartość wpisana w kreatorze bez Enter jest wartością warunku —
 * klik „Zastosuj"/„Zapisz" (utrata fokusu) nie może użyć starej wartości. Dla operatorów
 * skalarnych combobox `freeSolo` commituje wpis na bieżąco; listy (`in`/`not in`) zostają
 * przy chipach — Enter dodaje element, blur bez Enter niczego nie dodaje.
 */
import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import {
  FIXTURE_SUMMARY,
  MANUAL_FILTER,
  renderBuilder,
  useSummary,
} from '../../test/metadataBuilder'

import { convertConditionValue } from './ConditionRow'

afterEach(cleanup)

describe('ConditionRow — wartość wpisana bez Enter (T10)', () => {
  it('operator skalarny: wpis „ustawa" bez Enter jest w warunku po kliku poza kreatorem', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder(MANUAL_FILTER)
    const user = userEvent.setup()

    const valueBox = await within(screen.getByRole('group', { name: 'Warunek 1' })).findByRole(
      'combobox',
      { name: 'Wartość' },
    )
    await user.clear(valueBox)
    await user.type(valueBox, 'ustawa')
    await user.click(document.body)
    expect(onChange).toHaveBeenLastCalledWith({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: '=', value: 'ustawa' }],
    })
  })

  it('lista (`in`): blur bez Enter nie dodaje chipa (Enter pozostaje drogą dodania)', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onChange } = await renderBuilder({
      ...MANUAL_FILTER,
      manual: [{ key: 'typ', op: 'in', value: ['raport'] }],
    })
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Wartość'), 'ustawa')
    await user.click(document.body)
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('convertConditionValue — lista przy zmianie operatora (MINOR E6-1b T3a)', () => {
  it('`in` → `=` → `in` zachowuje elementy listy zamiast sklejać je w „a, b”', () => {
    const scalar = convertConditionValue(['a', 'b'], '=')
    expect(scalar).toBe('a, b')
    expect(convertConditionValue(scalar, 'in')).toEqual(['a', 'b'])
    expect(convertConditionValue('', 'in')).toEqual([])
  })
})
