import { describe, expect, it } from 'vitest'

import { EMPTY_META_FILTER } from '../../metadata/types'

import {
  DEFAULT_SETTINGS,
  RETRIEVAL_LANGUAGES,
  formatPercent,
  isMetaFilterActive,
  parseHighlight,
  questionSchema,
  settingsSchema,
} from './schema'

describe('DEFAULT_SETTINGS', () => {
  it('ma wartości domyślne z kontraktu', () => {
    expect(DEFAULT_SETTINGS).toEqual({
      similarityThreshold: 0.2,
      vectorWeight: 0.3,
      topN: 10,
      rerankId: '',
      crossLanguages: [],
      metaDataFilter: EMPTY_META_FILTER,
    })
  })
})

describe('RETRIEVAL_LANGUAGES', () => {
  it('niesie nazwy języków z upstreamu w kolejności kontraktu', () => {
    expect(RETRIEVAL_LANGUAGES).toEqual([
      'English',
      'Chinese',
      'Spanish',
      'French',
      'German',
      'Japanese',
      'Korean',
      'Vietnamese',
      'Arabic',
      'Turkish',
      'Dutch',
    ])
  })
})

describe('settingsSchema', () => {
  it('przyjmuje wartości domyślne', () => {
    expect(settingsSchema.safeParse(DEFAULT_SETTINGS).success).toBe(true)
  })

  it('odrzuca topN spoza zakresu 1–100', () => {
    expect(settingsSchema.safeParse({ ...DEFAULT_SETTINGS, topN: 101 }).success).toBe(false)
    expect(settingsSchema.safeParse({ ...DEFAULT_SETTINGS, topN: 0 }).success).toBe(false)
    expect(settingsSchema.safeParse({ ...DEFAULT_SETTINGS, topN: 1.5 }).success).toBe(false)
  })

  it('przyjmuje granice topN', () => {
    expect(settingsSchema.safeParse({ ...DEFAULT_SETTINGS, topN: 1 }).success).toBe(true)
    expect(settingsSchema.safeParse({ ...DEFAULT_SETTINGS, topN: 100 }).success).toBe(true)
  })

  it('przyjmuje listę języków, odrzuca nie-listę (K4)', () => {
    expect(
      settingsSchema.safeParse({ ...DEFAULT_SETTINGS, crossLanguages: ['German'] }).success,
    ).toBe(true)
    expect(
      settingsSchema.safeParse({ ...DEFAULT_SETTINGS, crossLanguages: 'German' }).success,
    ).toBe(false)
  })

  it('odrzuca progi spoza zakresu 0–1', () => {
    expect(
      settingsSchema.safeParse({ ...DEFAULT_SETTINGS, similarityThreshold: 1.1 }).success,
    ).toBe(false)
    expect(
      settingsSchema.safeParse({ ...DEFAULT_SETTINGS, similarityThreshold: -0.1 }).success,
    ).toBe(false)
    expect(settingsSchema.safeParse({ ...DEFAULT_SETTINGS, vectorWeight: 2 }).success).toBe(false)
    expect(settingsSchema.safeParse({ ...DEFAULT_SETTINGS, vectorWeight: 0 }).success).toBe(true)
    expect(settingsSchema.safeParse({ ...DEFAULT_SETTINGS, similarityThreshold: 1 }).success).toBe(
      true,
    )
  })
})

describe('isMetaFilterActive', () => {
  it('off i ręczny bez warunków nie filtrują (kontrakt §1: wyłączony = {})', () => {
    expect(isMetaFilterActive(EMPTY_META_FILTER)).toBe(false)
    expect(isMetaFilterActive({ ...EMPTY_META_FILTER, method: 'manual', manual: [] })).toBe(false)
  })

  it('ręczny z warunkiem i tryby modelu filtrują', () => {
    expect(
      isMetaFilterActive({
        ...EMPTY_META_FILTER,
        method: 'manual',
        manual: [{ key: 'typ', op: '=', value: 'raport' }],
      }),
    ).toBe(true)
    expect(isMetaFilterActive({ ...EMPTY_META_FILTER, method: 'auto' })).toBe(true)
    expect(
      isMetaFilterActive({ ...EMPTY_META_FILTER, method: 'semi_auto', semi_auto: ['rok'] }),
    ).toBe(true)
  })
})

describe('settingsSchema — metaDataFilter', () => {
  it('przyjmuje filtr ręczny z warunkiem', () => {
    const settings = {
      ...DEFAULT_SETTINGS,
      metaDataFilter: {
        ...EMPTY_META_FILTER,
        method: 'manual' as const,
        manual: [{ key: 'typ', op: '=' as const, value: 'raport' }],
      },
    }
    expect(settingsSchema.safeParse(settings).success).toBe(true)
  })
})

describe('questionSchema', () => {
  it('przycina białe znaki', () => {
    expect(questionSchema.parse('  pytanie  ')).toBe('pytanie')
  })

  it('odrzuca pytanie puste po przycięciu', () => {
    expect(questionSchema.safeParse('').success).toBe(false)
    expect(questionSchema.safeParse('   ').success).toBe(false)
  })

  it('przyjmuje niepuste pytanie', () => {
    expect(questionSchema.safeParse('co to jest RAG?').success).toBe(true)
  })
})

describe('formatPercent', () => {
  it('formatuje ułamek jako procent z jednym miejscem po przecinku', () => {
    expect(formatPercent(0.85)).toBe('85.0')
    expect(formatPercent(0.123456)).toBe('12.3')
    expect(formatPercent(0)).toBe('0.0')
    expect(formatPercent(1)).toBe('100.0')
  })
})

describe('parseHighlight', () => {
  it('dzieli tekst na części bez HTML', () => {
    expect(parseHighlight('a <em>b</em> c')).toEqual([
      { text: 'a ', match: false },
      { text: 'b', match: true },
      { text: ' c', match: false },
    ])
  })

  it('usuwa tagi inne niż <em>, zostawiając tekst', () => {
    expect(parseHighlight('x <b>y</b>')).toEqual([{ text: 'x y', match: false }])
  })

  it('zwraca pustą listę dla null i pustego tekstu', () => {
    expect(parseHighlight(null)).toEqual([])
    expect(parseHighlight(undefined)).toEqual([])
    expect(parseHighlight('')).toEqual([])
  })

  it('nie zwraca pustych części', () => {
    expect(parseHighlight('<em>b</em>')).toEqual([{ text: 'b', match: true }])
    expect(parseHighlight('<em></em>')).toEqual([])
  })
})
