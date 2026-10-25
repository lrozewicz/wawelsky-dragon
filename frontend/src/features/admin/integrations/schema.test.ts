/**
 * Formularz integracji (kontrakt WP E4-3c §1): reguły `validateForm` w trybach create/edit,
 * mapowanie na ciała żądań WD (MB → bajty, trim, pominięcie pustego sekretu).
 */

import { describe, expect, it } from 'vitest'

import { makeIntegration } from '../../../test/msw/handlers'

import type { IntegrationFormValues } from './schema'
import {
  DEFAULT_FORM_VALUES,
  formValuesFromIntegration,
  toCreateBody,
  toSavedTestBody,
  toTestBody,
  toUpdateBody,
  validateForm,
} from './schema'

const REQUIRED = 'integrations.validation.required'
const SITE_URL = 'integrations.validation.siteUrl'
const INTERVAL = 'integrations.validation.interval'
const MAX_SIZE = 'integrations.validation.maxSize'

/** Poprawne wartości formularza — baza dla przypadków negatywnych. */
const VALID: IntegrationFormValues = {
  name: 'Dokumenty zespołu',
  dataset_id: 'ds-1',
  tenant_id: 'tenant-1',
  client_id: 'client-1',
  client_secret: 'sekret-1',
  site_url: 'https://contoso.sharepoint.com/sites/zespol',
  excluded_library_names: ['Szablony'],
  ignored_extensions: ['.tmp'],
  max_file_size_mb: 200,
  scan_interval_seconds: 300,
  delete_propagation: true,
  is_active: true,
}

describe('validateForm', () => {
  it('w trybie create wymaga wszystkich pól obowiązkowych', () => {
    expect(validateForm({ ...DEFAULT_FORM_VALUES }, 'create')).toEqual({
      name: REQUIRED,
      dataset_id: REQUIRED,
      tenant_id: REQUIRED,
      client_id: REQUIRED,
      client_secret: REQUIRED,
      site_url: REQUIRED,
    })
  })

  it('przyjmuje poprawne wartości w obu trybach', () => {
    expect(validateForm(VALID, 'create')).toEqual({})
    expect(validateForm(VALID, 'edit')).toEqual({})
  })

  it('w trybie edit pusty sekret jest poprawny, a w create wymagany', () => {
    expect(validateForm({ ...VALID, client_secret: '' }, 'edit')).toEqual({})
    expect(validateForm({ ...VALID, client_secret: '' }, 'create')).toEqual({
      client_secret: REQUIRED,
    })
  })

  it('pola tekstowe liczy po przycięciu białych znaków', () => {
    expect(validateForm({ ...VALID, name: '   ' }, 'create')).toEqual({ name: REQUIRED })
    expect(validateForm({ ...VALID, name: '  Dokumenty  ' }, 'create')).toEqual({})
  })

  it('adres witryny musi zaczynać się od https://', () => {
    expect(validateForm({ ...VALID, site_url: 'http://contoso.example' }, 'create')).toEqual({
      site_url: SITE_URL,
    })
    expect(validateForm({ ...VALID, site_url: 'https://contoso.example' }, 'create')).toEqual({})
  })

  it.each([
    [29, INTERVAL],
    [30.5, INTERVAL],
    [30, undefined],
    [300, undefined],
  ])('interwał skanowania %s daje %s', (seconds, expected) => {
    const errors = validateForm({ ...VALID, scan_interval_seconds: seconds }, 'create')

    expect(errors.scan_interval_seconds).toBe(expected)
  })

  it.each([
    [0, MAX_SIZE],
    [-5, MAX_SIZE],
    [0.5, undefined],
  ])('rozmiar pliku %s MB daje %s', (mb, expected) => {
    const errors = validateForm({ ...VALID, max_file_size_mb: mb }, 'create')

    expect(errors.max_file_size_mb).toBe(expected)
  })
})

describe('formValuesFromIntegration', () => {
  it('nie wypełnia sekretu i przelicza bajty na MB', () => {
    const values = formValuesFromIntegration(
      makeIntegration({ name: 'Zespołowa', max_file_size_bytes: 1048576 }),
    )

    expect(values.name).toBe('Zespołowa')
    expect(values.client_secret).toBe('')
    expect(values.max_file_size_mb).toBe(1)
  })
})

describe('toCreateBody', () => {
  it('przycina tekst, ustawia typ i przelicza MB na bajty', () => {
    const body = toCreateBody({
      ...VALID,
      name: '  Dokumenty  ',
      site_url: ' https://contoso.example ',
      max_file_size_mb: 1,
    })

    expect(body).toMatchObject({
      type: 'sharepoint',
      name: 'Dokumenty',
      site_url: 'https://contoso.example',
      max_file_size_bytes: 1048576,
      client_secret: 'sekret-1',
      excluded_library_names: ['Szablony'],
    })
  })
})

describe('toUpdateBody', () => {
  it('pomija klucz sekretu, gdy pole jest puste', () => {
    const body = toUpdateBody({ ...VALID, client_secret: '' })

    expect(body).not.toHaveProperty('client_secret')
    expect(body).toMatchObject({ type: 'sharepoint', name: 'Dokumenty zespołu' })
  })

  it('niesie sekret, gdy użytkownik go wpisał', () => {
    expect(toUpdateBody(VALID)).toMatchObject({ client_secret: 'sekret-1' })
  })
})

describe('toTestBody i toSavedTestBody', () => {
  it('test bez zapisu wysyła komplet pól połączenia', () => {
    const body = toTestBody({ ...VALID, tenant_id: ' tenant-1 ' })

    expect(body).toEqual({
      type: 'sharepoint',
      tenant_id: 'tenant-1',
      client_id: 'client-1',
      client_secret: 'sekret-1',
      site_url: 'https://contoso.sharepoint.com/sites/zespol',
      dataset_id: 'ds-1',
      excluded_library_names: ['Szablony'],
    })
  })

  it('test zapisanej integracji pomija pusty sekret i nie niesie typu', () => {
    const empty = toSavedTestBody({ ...VALID, client_secret: '' })
    const filled = toSavedTestBody(VALID)

    expect(empty).not.toHaveProperty('client_secret')
    expect(empty).not.toHaveProperty('type')
    expect(empty).toMatchObject({ tenant_id: 'tenant-1', dataset_id: 'ds-1' })
    expect(filled).toMatchObject({ client_secret: 'sekret-1' })
  })
})
