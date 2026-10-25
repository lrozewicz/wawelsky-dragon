import { isRedirect } from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'

import { fixtureUser } from '../test/msw/handlers'
import { requireSession, requireSuperuser } from './guards'

// Badany obiekt przekierowania to `Response` z dołożonymi `options` (router-core/redirect.ts).
type RedirectShape = { options: { to?: string; search?: { redirect?: string } } }

const location = { href: 'http://localhost/datasets?page=2' }

function captureSync(fn: () => void): unknown {
  try {
    fn()
    return null
  } catch (error) {
    return error
  }
}

async function captureAsync(fn: () => Promise<void>): Promise<unknown> {
  try {
    await fn()
    return null
  } catch (error) {
    return error
  }
}

describe('requireSession', () => {
  it('brak sesji → redirect na /login z powrotem do bieżącego adresu', async () => {
    const error = await captureAsync(() =>
      requireSession({ ensureSession: async () => null }, location),
    )

    expect(isRedirect(error)).toBe(true)
    expect((error as RedirectShape).options.to).toBe('/login')
    expect((error as RedirectShape).options.search).toEqual({ redirect: location.href })
  })

  it('sesja jest → nie rzuca', async () => {
    const auth = { ensureSession: async () => fixtureUser }

    await expect(requireSession(auth, location)).resolves.toBeUndefined()
  })
})

describe('requireSuperuser', () => {
  it('brak użytkownika → redirect na /', () => {
    const error = captureSync(() => requireSuperuser({ user: null }))

    expect(isRedirect(error)).toBe(true)
    expect((error as RedirectShape).options.to).toBe('/')
  })

  it('użytkownik bez uprawnień superusera → redirect na /', () => {
    const error = captureSync(() =>
      requireSuperuser({ user: { ...fixtureUser, is_superuser: false } }),
    )

    expect(isRedirect(error)).toBe(true)
    expect((error as RedirectShape).options.to).toBe('/')
  })

  it('superuser → nie rzuca', () => {
    expect(() => requireSuperuser({ user: { ...fixtureUser, is_superuser: true } })).not.toThrow()
  })
})
