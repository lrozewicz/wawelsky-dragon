/**
 * `meta_data_filter` w schemacie ustawień czatu (WP E6-1b): odczyt drutu przez `filterFromWire`
 * i dołączenie filtra do łatki PATCH przez `filterToWire`. Osobny plik, bo
 * `schema.test.ts` siedzi na limicie `max-lines` (DEC-098).
 */

import { describe, expect, it } from 'vitest'

import { chatDetail } from '../../../test/msw/handlers'

import { buildPatch, chatSettingsSchema, chatToFormValues } from './schema'

/** Czat bazowy (atrapa z MSW), jak w `schema.test.ts`. */
function makeValues() {
  return chatToFormValues(chatDetail({ name: 'Alfa', description: 'Opis', dataset_ids: [] }))
}

const MANUAL_FILTER = {
  method: 'manual' as const,
  logic: 'and' as const,
  manual: [{ key: 'typ', op: '=' as const, value: 'raport' }],
  semi_auto: [] as string[],
}

describe('meta_data_filter (E6-1b)', () => {
  it('chatToFormValues czyta drut przez filterFromWire: `{}` → filtr wyłączony', () => {
    expect(makeValues().metaDataFilter).toEqual({
      method: 'off',
      logic: 'and',
      manual: [],
      semi_auto: [],
    })
    expect(
      chatToFormValues(chatDetail({ meta_data_filter: MANUAL_FILTER })).metaDataFilter,
    ).toEqual(MANUAL_FILTER)
  })

  it('buildPatch: brak zmian bez klucza; zmiana ręczna warunki, wyłączenie `{}`', () => {
    const initial = makeValues()
    expect(buildPatch(initial, { ...initial, metaDataFilter: MANUAL_FILTER })).toEqual({
      meta_data_filter: { method: 'manual', logic: 'and', manual: MANUAL_FILTER.manual },
    })
    const withFilter = chatToFormValues(chatDetail({ meta_data_filter: MANUAL_FILTER }))
    expect(
      buildPatch(withFilter, {
        ...withFilter,
        metaDataFilter: { ...withFilter.metaDataFilter, method: 'off' as const, manual: [] },
      }),
    ).toEqual({ meta_data_filter: {} })
  })

  it('walidacja: warunek ręczny bez klucza nie przechodzi — komunikat przy polu (T6 c)', () => {
    const values = chatToFormValues(chatDetail({ meta_data_filter: MANUAL_FILTER }))
    expect(chatSettingsSchema.safeParse(values).success).toBe(true)

    const emptyKey = {
      ...values,
      metaDataFilter: {
        ...values.metaDataFilter,
        manual: [{ key: '   ', op: '=' as const, value: 'raport' }],
      },
    }
    const parsed = chatSettingsSchema.safeParse(emptyKey)
    expect(parsed.success).toBe(false)
    const issue = parsed.success
      ? undefined
      : parsed.error.issues.find((item) => item.path[0] === 'metaDataFilter')
    expect(issue?.message).toBe('chat.settings.filterKeyRequired')
    expect(issue?.path.map(String)).toEqual(['metaDataFilter', 'manual', '0', 'key'])
  })

  it('pusta wartość warunku (SC-E67-06 k4): błąd `filterValueRequired`, ale nie dla `empty`', () => {
    const values = makeValues()
    const withOp = (op: '=' | 'empty' | 'in', value: string | string[]) => ({
      ...values,
      metaDataFilter: {
        ...MANUAL_FILTER,
        manual: [{ key: 'typ', op, value }],
      },
    })
    const messages = (input: ReturnType<typeof withOp>) => {
      const parsed = chatSettingsSchema.safeParse(input)
      return parsed.success ? [] : parsed.error.issues.map((item) => item.message)
    }
    expect(messages(withOp('=', ''))).toContain('chat.settings.filterValueRequired')
    expect(messages(withOp('in', []))).toContain('chat.settings.filterValueRequired')
    expect(messages(withOp('empty', ''))).toEqual([])
    expect(messages(withOp('=', 'raport'))).toEqual([])
  })
})
