/** Brzeg „Ręczny" na bazie BEZ metadanych (review E6-1b-T6 MAJOR 1): pusty warunek szedłby
 * z zapisem do meta_data_filter, a backend odrzuca każde pytanie czatu kodem 400 (walidacja
 * klucza) — dlatego kreator zostawia `manual: []`; osobny plik (wzorzec DEC-098). */
import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it } from 'vitest'

import { renderBuilder, useSummary } from '../../test/metadataBuilder'

import { EMPTY_META_FILTER } from './types'

afterEach(cleanup)

it('baza bez metadanych: „Ręczny” bez warunków — pusty warunek dałby 400 backendu przy pytaniu', async () => {
  useSummary({})
  const { onChange } = await renderBuilder(EMPTY_META_FILTER)

  await userEvent.setup().click(screen.getByRole('radio', { name: 'Ręczny' }))
  expect(onChange).toHaveBeenLastCalledWith({ ...EMPTY_META_FILTER, method: 'manual', manual: [] })
})
