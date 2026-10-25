import { describe, expect, it } from 'vitest'

import { canExport } from './canExport'

/** `fixtureUser` z MSW ma `id: 'u1'`, `is_superuser: false` — tu te same wartości dosłownie. */
const OWNER = { id: 'u1', is_superuser: false }
const MEMBER = { id: 'u2', is_superuser: false }
const SUPERUSER = { id: 'u9', is_superuser: true }

describe('canExport', () => {
  it('właściciel bazy widzi pozycję eksportu', () => {
    expect(canExport({ tenant_id: 'u1' }, OWNER)).toBe(true)
  })

  it('członek zespołu przy cudzej bazie — bez pozycji (SC-E7-2-05 krok 1)', () => {
    expect(canExport({ tenant_id: 'u1' }, MEMBER)).toBe(false)
  })

  it('superuser widzi pozycję przy cudzej bazie (SC-E7-2-05 krok 2)', () => {
    expect(canExport({ tenant_id: 'u1' }, SUPERUSER)).toBe(true)
  })

  it('superuser przy własnej bazie też widzi pozycję', () => {
    expect(canExport({ tenant_id: 'u9' }, SUPERUSER)).toBe(true)
  })
})
