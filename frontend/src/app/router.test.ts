import { describe, expect, it } from 'vitest'

import { routeTree } from '../routeTree.gen'

import { queryClient } from './queryClient'
import { auth, router } from './router'

describe('router aplikacji', () => {
  it('niesie sesję i klienta zapytań w kontekście', () => {
    expect(router.options.context.auth).toBe(auth)
    expect(router.options.context.queryClient).toBe(queryClient)
    expect(router.options.defaultPreload).toBe('intent')
  })

  it('korzysta z wygenerowanego drzewa tras', () => {
    expect(router.routeTree).toBe(routeTree)
  })
})
