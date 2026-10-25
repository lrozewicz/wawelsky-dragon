import { describe, expect, it } from 'vitest'

import {
  conditionsToDocumentsParam,
  fieldsFromWire,
  fieldsToWire,
  filterFromWire,
  filterToWire,
  metaToRows,
  rowsToMeta,
  summarizeMeta,
  validateFieldDefs,
} from './convert'
import { EMPTY_META_FILTER } from './types'
import type { MetaCondition, MetaFieldDef, MetaFilter } from './types'

// Fabryka pola formularza: przykłady z briefu podają sam klucz.
const def = (key: string, rest: Partial<MetaFieldDef> = {}): MetaFieldDef => ({
  key,
  description: '',
  enum: [],
  ...rest,
})

const filter = (rest: Partial<MetaFilter> = {}): MetaFilter => ({
  method: 'off',
  logic: 'and',
  manual: [],
  semi_auto: [],
  ...rest,
})

describe('filterToWire', () => {
  it('wyłączony filtr to puste ciało', () => {
    expect(filterToWire(filter({ method: 'off' }))).toEqual({})
  })

  it('ręczny niesie logikę i warunki', () => {
    const value = filter({
      method: 'manual',
      manual: [{ key: 'typ', op: '=', value: 'raport' }],
    })
    expect(filterToWire(value)).toEqual({
      method: 'manual',
      logic: 'and',
      manual: [{ key: 'typ', op: '=', value: 'raport' }],
    })
  })

  it('warunek bez wartości niesie puste `value`', () => {
    const value = filter({ method: 'manual', manual: [{ key: 'y', op: 'empty', value: '' }] })
    expect(filterToWire(value)).toEqual({
      method: 'manual',
      logic: 'and',
      manual: [{ key: 'y', op: 'empty', value: '' }],
    })
  })

  it('automatyczny i półautomatyczny mają własne kształty', () => {
    expect(filterToWire(filter({ method: 'auto', logic: 'or' }))).toEqual({ method: 'auto' })
    expect(filterToWire(filter({ method: 'semi_auto', semi_auto: ['rok'] }))).toEqual({
      method: 'semi_auto',
      semi_auto: ['rok'],
    })
  })
})

describe('filterFromWire', () => {
  it('null, pusty obiekt i nieznana metoda dają pusty filtr', () => {
    expect(filterFromWire(null)).toEqual(EMPTY_META_FILTER)
    expect(filterFromWire(undefined)).toEqual(EMPTY_META_FILTER)
    expect(filterFromWire({})).toEqual(EMPTY_META_FILTER)
    expect(filterFromWire({ method: 'nonsense' })).toEqual(EMPTY_META_FILTER)
  })

  it('czyta warunki ręczne, tolerując śmieci i skróty', () => {
    const raw = {
      method: 'manual',
      logic: 'or',
      manual: [
        { key: 'typ', op: '=', value: 'raport' },
        { key: 'x', op: 'in', value: ['a', 'b'] },
        { key: 'y', op: 'empty', value: '' },
        'junk',
        { key: '', op: '=', value: 'x' },
        { key: 'z', op: '???', value: 'x' },
        { key: 'w', op: '=', value: 5 },
        { key: 'v', op: '=', value: ['a', 1] },
      ],
    }
    expect(filterFromWire(raw)).toEqual({
      method: 'manual',
      logic: 'or',
      manual: [
        { key: 'typ', op: '=', value: 'raport' },
        { key: 'x', op: 'in', value: ['a', 'b'] },
        { key: 'y', op: 'empty', value: '' },
        { key: 'v', op: '=', value: ['a', '1'] },
      ],
      semi_auto: [],
    })
  })

  it('ręczny bez listy warunków i bez logiki daje pustą listę, logikę and', () => {
    expect(filterFromWire({ method: 'manual' })).toEqual({
      method: 'manual',
      logic: 'and',
      manual: [],
      semi_auto: [],
    })
  })

  it('półautomatyczny filtruje nie-tekstowe klucze, brak listy → pusto', () => {
    expect(filterFromWire({ method: 'semi_auto', semi_auto: ['rok', 5] })).toEqual({
      method: 'semi_auto',
      logic: 'and',
      manual: [],
      semi_auto: ['rok'],
    })
    expect(filterFromWire({ method: 'semi_auto' })).toEqual({
      method: 'semi_auto',
      logic: 'and',
      manual: [],
      semi_auto: [],
    })
  })

  it('automatyczny zachowuje logikę', () => {
    expect(filterFromWire({ method: 'auto', logic: 'or' })).toEqual({
      method: 'auto',
      logic: 'or',
      manual: [],
      semi_auto: [],
    })
  })
})

describe('conditionsToDocumentsParam', () => {
  it('buduje JSON `?metadata_condition=` wg kontraktu §2', () => {
    const conds: MetaCondition[] = [
      { key: 'typ', op: '=', value: 'raport' },
      { key: 'x', op: 'in', value: ['a', 'b'] },
      { key: 'y', op: 'empty', value: '' },
    ]
    expect(conditionsToDocumentsParam('and', conds)).toBe(
      '{"logic":"and","conditions":[{"name":"typ","comparison_operator":"=","value":"raport"},' +
        '{"name":"x","comparison_operator":"in","value":["a","b"]},' +
        '{"name":"y","comparison_operator":"empty","value":""}]}',
    )
  })

  it('pusta lista i same warunki bez klucza dają undefined', () => {
    expect(conditionsToDocumentsParam('and', [])).toBeUndefined()
    expect(conditionsToDocumentsParam('or', [{ key: '   ', op: '=', value: 'x' }])).toBeUndefined()
  })
})

describe('validateFieldDefs', () => {
  it('zwraca status po indeksie wg briefu', () => {
    expect(validateFieldDefs([def('rok'), def('rok'), def('')])).toEqual([
      'ok',
      'duplicate',
      'required',
    ])
  })

  it('klucz porównuje po trim, wielkość liter istotna', () => {
    expect(validateFieldDefs([def('rok'), def(' rok '), def('Rok')])).toEqual([
      'ok',
      'duplicate',
      'ok',
    ])
  })
})

describe('fieldsFromWire / fieldsToWire', () => {
  it('null z drutu zamienia na puste pola formularza', () => {
    expect(fieldsFromWire([{ key: 'rok', description: null, enum: null }])).toEqual([
      { key: 'rok', description: '', enum: [] },
    ])
    expect(fieldsFromWire([{ key: 'typ', description: 'opis', enum: ['a'] }])).toEqual([
      { key: 'typ', description: 'opis', enum: ['a'] },
    ])
  })

  it('pusty opis i brak wartości idą do drutu jako null, klucz po trim', () => {
    expect(fieldsToWire([def(' rok '), def('typ', { description: 'opis', enum: ['a'] })])).toEqual([
      { key: 'rok', type: 'string', description: null, enum: null },
      { key: 'typ', type: 'string', description: 'opis', enum: ['a'] },
    ])
  })
})

describe('summarizeMeta', () => {
  it('buduje teksty `klucz: wartość` w kolejności kluczy', () => {
    const rows = summarizeMeta({ rok: '2023', tagi: ['a', 'b'], n: 5 })
    expect(rows.map((row) => row.text)).toEqual(['rok: 2023', 'tagi: a, b', 'n: 5'])
    expect(rows.map((row) => row.key)).toEqual(['rok', 'tagi', 'n'])
    expect(rows[1]?.full).toBe('tagi: a, b')
  })

  it('null/undefined i brak słownika dają pustą listę lub pustą wartość', () => {
    expect(summarizeMeta(null)).toEqual([])
    expect(summarizeMeta({ brak: null, brak2: undefined }).map((row) => row.text)).toEqual([
      'brak: ',
      'brak2: ',
    ])
  })
})

describe('metaToRows / rowsToMeta', () => {
  it('brak metadanych daje pustą listę wierszy', () => {
    expect(metaToRows(null)).toEqual([])
  })

  it('lista wartości staje się string[], reszta tekstem', () => {
    expect(metaToRows({ n: 5, tagi: ['a', 'b'], s: 'x' })).toEqual([
      { key: 'n', value: '5', untouched: 5 },
      { key: 'tagi', value: ['a', 'b'], untouched: ['a', 'b'] },
      { key: 's', value: 'x', untouched: 'x' },
    ])
  })

  it('wartość nietknięta zachowuje typ, edytowana idzie jako tekst', () => {
    expect(rowsToMeta([{ key: 'n', value: '5', untouched: 5 }])).toEqual({ n: 5 })
    expect(rowsToMeta([{ key: 'b', value: 'true', untouched: true }])).toEqual({ b: true })
    expect(rowsToMeta([{ key: 'n', value: '6', untouched: 5 }])).toEqual({ n: '6' })
    expect(rowsToMeta([{ key: 's', value: 'x', untouched: 'x' }])).toEqual({ s: 'x' })
    expect(rowsToMeta([{ key: 'tagi', value: ['a', 'b'], untouched: ['a', 'b'] }])).toEqual({
      tagi: ['a', 'b'],
    })
  })

  it('puste (po trim) klucze są pomijane, a round-trip zachowuje liczbę', () => {
    expect(rowsToMeta([{ key: '   ', value: 'x', untouched: 'x' }])).toEqual({})
    expect(rowsToMeta(metaToRows({ n: 5 }))).toEqual({ n: 5 })
  })
})
