import { describe, expect, it } from 'vitest'

import { parseFeatureFlags } from './featureFlags'

describe('parseFeatureFlags', () => {
  it.each([
    ['puste środowisko', {}, { agent: false, memory: false, search: false, files: false }],
    [
      'FEATURE_AGENT: true',
      { FEATURE_AGENT: true },
      { agent: true, memory: false, search: false, files: false },
    ],
    [
      'FEATURE_MEMORY: "true"',
      { FEATURE_MEMORY: 'true' },
      { agent: false, memory: true, search: false, files: false },
    ],
    [
      'FEATURE_SEARCH: "1"',
      { FEATURE_SEARCH: '1' },
      { agent: false, memory: false, search: true, files: false },
    ],
    [
      'FEATURE_FILES: "TRUE" (wielkie litery)',
      { FEATURE_FILES: 'TRUE' },
      { agent: false, memory: false, search: false, files: false },
    ],
    [
      'FEATURE_AGENT: 1 (liczba)',
      { FEATURE_AGENT: 1 },
      { agent: false, memory: false, search: false, files: false },
    ],
    [
      'FEATURE_AGENT: "false", FEATURE_FILES: "0"',
      { FEATURE_AGENT: 'false', FEATURE_FILES: '0' },
      { agent: false, memory: false, search: false, files: false },
    ],
    [
      'FEATURE_AGENT: "yes"',
      { FEATURE_AGENT: 'yes' },
      { agent: false, memory: false, search: false, files: false },
    ],
    [
      'wszystkie flagi true',
      { FEATURE_AGENT: '1', FEATURE_MEMORY: true, FEATURE_SEARCH: 'true', FEATURE_FILES: '1' },
      { agent: true, memory: true, search: true, files: true },
    ],
    [
      'obcy klucz OTHER',
      { OTHER: 'true' },
      { agent: false, memory: false, search: false, files: false },
    ],
  ])('%s', (_name, env, expected) => {
    expect(parseFeatureFlags(env)).toEqual(expected)
  })
})
