import { describe, expect, it } from 'vitest'

import { AUTO_PROVISIONED_SUFFIX, isAutoProvisioned } from './constants'

describe('isAutoProvisioned', () => {
  it('rozpoznaje markera po sufiksie', () => {
    expect(isAutoProvisioned('hub-compat-auto-provisioning')).toBe(true)
    expect(isAutoProvisioned(`produkt${AUTO_PROVISIONED_SUFFIX}`)).toBe(true)
  })

  it('odrzuca pozostałe wartości', () => {
    expect(isAutoProvisioned('admin@wd.test')).toBe(false)
    expect(isAutoProvisioned(null)).toBe(false)
    expect(isAutoProvisioned(undefined)).toBe(false)
    expect(isAutoProvisioned('')).toBe(false)
  })
})
