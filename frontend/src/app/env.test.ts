import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { ENV_KEYS, getEnv, getFeatureFlags, readEnv, resetEnvCache } from './env'

// prefiks komunikatu wymagany przez kontrakt C4 (env.ts)
const PREFIX = 'Nieprawidłowa konfiguracja środowiska:'

describe('ENV_KEYS', () => {
  it('to osiem kluczy kontraktu C4', () => {
    expect(ENV_KEYS).toEqual([
      'KEYCLOAK_URL',
      'KEYCLOAK_REALM',
      'KEYCLOAK_CLIENT_ID',
      'DOCS_URL',
      'FEATURE_AGENT',
      'FEATURE_MEMORY',
      'FEATURE_SEARCH',
      'FEATURE_FILES',
    ])
  })
})

describe('readEnv', () => {
  it('windowEnv: podane wartości przechodzą, brakujące → ""', () => {
    const env = readEnv({ windowEnv: { DOCS_URL: 'https://d', FEATURE_AGENT: 'true' } })
    expect(env.DOCS_URL).toBe('https://d')
    expect(env.FEATURE_AGENT).toBe('true')
    expect(env.KEYCLOAK_URL).toBe('')
  })

  it('windowEnv: undefined → fallback na metaEnv pod kluczami VITE_<KEY>', () => {
    const env = readEnv({ windowEnv: undefined, metaEnv: { VITE_DOCS_URL: 'https://m' } })
    expect(env.DOCS_URL).toBe('https://m')
    expect(env.KEYCLOAK_URL).toBe('')
  })

  it('windowEnv: undefined i brak metaEnv → wszystkie klucze ""', () => {
    const env = readEnv()
    for (const key of ENV_KEYS) expect(env[key]).toBe('')
  })

  it('windowEnv: nieznane klucze są ignorowane', () => {
    const env = readEnv({ windowEnv: { DOCS_URL: 'https://d', OTHER: 'x' } })
    expect(env).toEqual({
      KEYCLOAK_URL: '',
      KEYCLOAK_REALM: '',
      KEYCLOAK_CLIENT_ID: '',
      DOCS_URL: 'https://d',
      FEATURE_AGENT: '',
      FEATURE_MEMORY: '',
      FEATURE_SEARCH: '',
      FEATURE_FILES: '',
    })
  })

  it('windowEnv z niepoprawnym typem wartości → Error z prefiksem', () => {
    expect(() => readEnv({ windowEnv: { DOCS_URL: 5 } })).toThrowError(new RegExp(`^${PREFIX}`))
  })

  it('windowEnv = "x" (nie-obiekt) → Error z prefiksem', () => {
    expect(() => readEnv({ windowEnv: 'x' })).toThrowError(new RegExp(`^${PREFIX}`))
  })

  it('windowEnv = null → Error z prefiksem', () => {
    expect(() => readEnv({ windowEnv: null })).toThrowError(new RegExp(`^${PREFIX}`))
  })

  it('windowEnv = 42 (nie-obiekt) → Error z prefiksem', () => {
    expect(() => readEnv({ windowEnv: 42 })).toThrowError(new RegExp(`^${PREFIX}`))
  })

  it('windowEnv = tablica → Error z prefiksem (tablica nie jest konfiguracją)', () => {
    expect(() => readEnv({ windowEnv: [] })).toThrowError(new RegExp(`^${PREFIX}`))
  })
})

describe('getEnv / resetEnvCache', () => {
  beforeEach(() => {
    resetEnvCache()
  })

  afterEach(() => {
    delete window.__ENV__
    resetEnvCache()
  })

  it('getEnv czyta window.__ENV__', () => {
    window.__ENV__ = { DOCS_URL: 'https://a' }
    expect(getEnv().DOCS_URL).toBe('https://a')
  })

  it('getEnv pamięciuje wynik, resetEnvCache czyści pamięć', () => {
    window.__ENV__ = { DOCS_URL: 'https://a' }
    expect(getEnv().DOCS_URL).toBe('https://a')
    window.__ENV__ = { DOCS_URL: 'https://b' }
    expect(getEnv().DOCS_URL).toBe('https://a')
    resetEnvCache()
    expect(getEnv().DOCS_URL).toBe('https://b')
  })

  it('getEnv bez window.__ENV__ → fallback na import.meta.env (VITE_* nieustawione → "")', () => {
    delete window.__ENV__
    expect(getEnv().DOCS_URL).toBe('')
    expect(getEnv().FEATURE_AGENT).toBe('')
  })
})

describe('getFeatureFlags', () => {
  beforeEach(() => {
    resetEnvCache()
  })

  afterEach(() => {
    delete window.__ENV__
    resetEnvCache()
  })

  it('czyta flagi z window.__ENV__', () => {
    window.__ENV__ = { FEATURE_AGENT: 'true', FEATURE_SEARCH: '1' }
    expect(getFeatureFlags()).toEqual({ agent: true, memory: false, search: true, files: false })
  })
})
