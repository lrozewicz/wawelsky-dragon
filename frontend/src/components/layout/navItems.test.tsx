import { describe, expect, it } from 'vitest'

import type { FeatureFlags } from '../../lib/featureFlags'

import { activeNavItem, visibleNavItems } from './navItems'

const HIDDEN: FeatureFlags = { agent: false, memory: false, search: true, files: true }

describe('visibleNavItems', () => {
  it('pokazuje tylko pozycje bazowe, gdy agent i pamięć wyłączone', () => {
    const keys = visibleNavItems({ isSuperuser: false, flags: HIDDEN }).map((item) => item.key)
    expect(keys).toEqual(['home', 'datasets', 'chat', 'search', 'files', 'settings'])
  })

  it('dokłada agenta i administrację dla superusera z flagą agenta', () => {
    const keys = visibleNavItems({
      isSuperuser: true,
      flags: { ...HIDDEN, agent: true },
    }).map((item) => item.key)
    expect(keys).toEqual([
      'home',
      'datasets',
      'chat',
      'search',
      'agent',
      'files',
      'settings',
      'admin',
    ])
  })
})

describe('activeNavItem', () => {
  it.each([
    ['/dataset/files/1', 'datasets'],
    ['/chunk/parsed/chunks', 'datasets'],
    ['/chat/7', 'chat'],
    ['/', 'home'],
    ['/user-setting/api', 'settings'],
  ])('dla %s zwraca %s', (pathname, key) => {
    expect(activeNavItem(pathname)?.key).toBe(key)
  })

  it('nie pasuje do ścieżki o wspólnym prefiksie bez separatora', () => {
    expect(activeNavItem('/datasetsX')).toBeUndefined()
  })
})
