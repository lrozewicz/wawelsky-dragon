/**
 * Formatowanie liczb UI transferu (MINOR T4): grupowanie 4-cyfrowych (pl-PL domyślnie pomija
 * grupę 1000–9999), twarda spacja między liczbą a jednostką rozmiaru i jako separator tysięcy.
 */

import { describe, expect, it } from 'vitest'

import { NUMBER_SPACE, formatGrouped, formatPackageBytes } from './format'

describe('formatGrouped', () => {
  it('grupuje także liczby 4-cyfrowe („7 251” jak w spec 08 §7.15)', () => {
    expect(formatGrouped(7251, 'pl')).toBe(`7${NUMBER_SPACE}251`)
    expect(formatGrouped(7251000, 'pl')).toBe(`7${NUMBER_SPACE}251${NUMBER_SPACE}000`)
  })

  it('małe liczby i angielski bez zmian poza standardowym grupowaniem', () => {
    expect(formatGrouped(3, 'pl')).toBe('3')
    expect(formatGrouped(41, 'pl')).toBe('41')
    expect(formatGrouped(7251, 'en')).toBe('7,251')
  })
})

describe('formatPackageBytes', () => {
  it('dobiera jednostkę i dzieli ją twardą spacją („74 MB” nie łamie się w 390 px)', () => {
    expect(formatPackageBytes(77_594_624, 'pl')).toBe(`74${NUMBER_SPACE}MB`)
    expect(formatPackageBytes(31_457_280, 'en')).toBe(`30${NUMBER_SPACE}MB`)
    expect(formatPackageBytes(512, 'pl')).toBe(`512${NUMBER_SPACE}B`)
    expect(formatPackageBytes(2 * 1024 ** 3, 'pl')).toBe(`2${NUMBER_SPACE}GB`)
  })

  it('zaokrągla do jednego miejsca po przecinku (wariant pl i en)', () => {
    expect(formatPackageBytes(1_572_864, 'pl')).toBe(`1,5${NUMBER_SPACE}MB`)
    expect(formatPackageBytes(1_572_864, 'en')).toBe(`1.5${NUMBER_SPACE}MB`)
  })
})
