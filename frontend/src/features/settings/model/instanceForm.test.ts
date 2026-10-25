/**
 * Logika formularza instancji (brief E3-6c1 T5b pkt 3): budowa ciała POST/PUT i normalizacja
 * adresu. Test kontraktowy: puste pole klucza = `api_key` NIE występuje w ciele, a maska
 * z odczytu nigdy nie jedzie jako nowa wartość (kontrakt §3).
 */

import { describe, expect, it } from 'vitest'

import { MASKED_API_KEY } from '../constants'
import type { ProviderInstanceDetail } from '../providerQueries'

import { buildInstanceCreate, buildInstanceUpdate, normalizeBaseUrl } from './instanceForm'

const detail: ProviderInstanceDetail = {
  id: 'inst-1',
  instance_name: 'litellm-test',
  provider_id: 'litellm',
  region: 'default',
  base_url: 'http://gateway.test/v1',
  api_key: MASKED_API_KEY,
  status: 'active',
  wd_managed: false,
}

describe('normalizeBaseUrl', () => {
  it('obcina końcowe ukośniki i spacje', () => {
    expect(normalizeBaseUrl('http://g/v1/')).toBe('http://g/v1')
    expect(normalizeBaseUrl('  https://g/v1//  ')).toBe('https://g/v1')
  })

  it('nie zamienia samego schematu w `http:`', () => {
    expect(normalizeBaseUrl('http://')).toBe('http://')
  })
})

describe('buildInstanceCreate', () => {
  it('pomija puste pole klucza (przykład briefu)', () => {
    const body = buildInstanceCreate({ name: 'A', baseUrl: 'http://g/v1/', apiKey: '' })
    expect(body).toEqual({ instance_name: 'A', base_url: 'http://g/v1' })
    expect('api_key' in body).toBe(false)
  })

  it('dołącza klucz, gdy wpisano wartość', () => {
    const body = buildInstanceCreate({ name: 'A', baseUrl: 'http://g/v1', apiKey: ' sekret ' })
    expect(body).toEqual({ instance_name: 'A', base_url: 'http://g/v1', api_key: 'sekret' })
  })
})

describe('buildInstanceUpdate', () => {
  it('puste pole klucza = brak `api_key` w ciele PUT (przykład briefu)', () => {
    const body = buildInstanceUpdate(
      { name: 'x', baseUrl: 'http://gateway.test/v1', apiKey: '' },
      detail,
    )
    expect(body).toEqual({ instance_name: 'x', base_url: 'http://gateway.test/v1' })
    expect('api_key' in body).toBe(false)
  })

  it('wpisany nowy klucz trafia do ciała PUT', () => {
    const body = buildInstanceUpdate(
      { name: 'x', baseUrl: 'http://gateway.test/v1', apiKey: 'nowy' },
      detail,
    )
    expect(body).toEqual({
      instance_name: 'x',
      base_url: 'http://gateway.test/v1',
      api_key: 'nowy',
    })
  })

  it('maska z odczytu nigdy nie jest wysyłana jako nowy klucz', () => {
    const body = buildInstanceUpdate(
      { name: 'x', baseUrl: 'http://gateway.test/v1', apiKey: MASKED_API_KEY },
      detail,
    )
    expect('api_key' in body).toBe(false)
  })
})
