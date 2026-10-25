import { describe, expect, it } from 'vitest'

import { OIDC_ERROR_SLUGS, oidcErrorKey } from './oidcErrors'

describe('oidcErrorKey', () => {
  it('mapuje znany slug na klucz i18n', () => {
    expect(oidcErrorKey('token_failed')).toBe('auth.oidcError.token_failed')
    expect(oidcErrorKey('invalid_state')).toBe('auth.oidcError.invalid_state')
  })

  it('mapuje każdy slug z listy', () => {
    for (const slug of OIDC_ERROR_SLUGS) {
      expect(oidcErrorKey(slug)).toBe(`auth.oidcError.${slug}`)
    }
  })

  it('nieznany slug sprowadza do komunikatu ogólnego', () => {
    expect(oidcErrorKey('x')).toBe('auth.oidcError.unknown')
    expect(oidcErrorKey('')).toBe('auth.oidcError.unknown')
  })
})
