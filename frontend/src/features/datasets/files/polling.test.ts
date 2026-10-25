import { describe, expect, it } from 'vitest'

import { shouldPoll } from './polling'

const running = { run: 'RUNNING' as const, progress: 0 }
const schedule = { run: 'SCHEDULE' as const, progress: 0 }
const unstart = { run: 'UNSTART' as const, progress: 0 }
const done = { run: 'DONE' as const, progress: 1 }
const fail = { run: 'FAIL' as const, progress: 0 }

describe('shouldPoll', () => {
  it('odpytuje, gdy dokument się parsuje (RUNNING albo SCHEDULE)', () => {
    expect(shouldPoll([running])).toBe(true)
    expect(shouldPoll([schedule])).toBe(true)
  })

  it('odpytuje przy częściowym postępie, także gdy run jest jeszcze UNSTART', () => {
    expect(shouldPoll([unstart, { run: 'UNSTART' as const, progress: 0.5 }])).toBe(true)
  })

  it('nie odpytuje dla stanów spoczynku i brzegów postępu', () => {
    expect(shouldPoll([done, fail])).toBe(false)
    expect(shouldPoll([{ run: 'UNSTART' as const, progress: 0 }])).toBe(false)
    expect(shouldPoll([{ run: 'UNSTART' as const, progress: 1 }])).toBe(false)
  })

  it('nie odpytuje pustej listy', () => {
    expect(shouldPoll([])).toBe(false)
  })
})
