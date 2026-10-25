/**
 * Formularz integracji SharePoint (kontrakt WP E4-3c §1): wartości formularza, domyślne
 * dane, walidacja zod (klucze i18n komunikatów) oraz mapowanie na ciała żądań WD.
 * `client_secret` jest w UI tylko do wpisania — przy edycji pusty oznacza „bez zmiany”.
 */

import { z } from 'zod'

import type { components } from '../../../api/schema.gen'

import type { Integration } from './queries'

export type IntegrationFormValues = {
  name: string
  dataset_id: string
  tenant_id: string
  client_id: string
  client_secret: string
  site_url: string
  excluded_library_names: string[]
  ignored_extensions: string[]
  /** Rozmiar pliku w MB (UI); ciało żądania niesie bajty. */
  max_file_size_mb: number
  scan_interval_seconds: number
  delete_propagation: boolean
  is_active: boolean
}

export const DEFAULT_FORM_VALUES: IntegrationFormValues = {
  name: '',
  dataset_id: '',
  tenant_id: '',
  client_id: '',
  client_secret: '',
  site_url: '',
  excluded_library_names: [],
  ignored_extensions: [],
  max_file_size_mb: 200,
  scan_interval_seconds: 300,
  delete_propagation: true,
  is_active: true,
}

/** Klucze i18n komunikatów walidacji (kontrakt §1) — `validateForm` zwraca właśnie je. */
const REQUIRED = 'integrations.validation.required'
const SITE_URL = 'integrations.validation.siteUrl'
const INTERVAL = 'integrations.validation.interval'
const MAX_SIZE = 'integrations.validation.maxSize'

/** MB → bajty, zaokrąglone jak w ciele żądania (kontrakt §1). */
function megabytesToBytes(mb: number): number {
  return Math.round(mb * 1024 * 1024)
}

/** Reguły formularza; sekret jest wymagany tylko przy tworzeniu (przy edycji pusty = bez zmiany). */
function formSchema(mode: 'create' | 'edit') {
  return z.object({
    name: z.string().trim().min(1, REQUIRED),
    dataset_id: z.string().trim().min(1, REQUIRED),
    tenant_id: z.string().trim().min(1, REQUIRED),
    client_id: z.string().trim().min(1, REQUIRED),
    client_secret: mode === 'create' ? z.string().min(1, REQUIRED) : z.string(),
    site_url: z
      .string()
      .trim()
      .min(1, REQUIRED)
      .refine((value) => value.startsWith('https://'), SITE_URL),
    excluded_library_names: z.array(z.string()),
    ignored_extensions: z.array(z.string()),
    max_file_size_mb: z.number().gt(0, MAX_SIZE),
    scan_interval_seconds: z.number().int(INTERVAL).min(30, INTERVAL),
    delete_propagation: z.boolean(),
    is_active: z.boolean(),
  })
}

/** Wypełnia formularz z zapisanej integracji — sekret zawsze pusty (nigdy go nie odczytujemy). */
export function formValuesFromIntegration(i: Integration): IntegrationFormValues {
  return {
    name: i.name,
    dataset_id: i.dataset_id,
    tenant_id: i.tenant_id,
    client_id: i.client_id,
    client_secret: '',
    site_url: i.site_url,
    excluded_library_names: [...i.excluded_library_names],
    ignored_extensions: [...i.ignored_extensions],
    max_file_size_mb: Math.round(i.max_file_size_bytes / (1024 * 1024)),
    scan_interval_seconds: i.scan_interval_seconds,
    delete_propagation: i.delete_propagation,
    is_active: i.is_active,
  }
}

/** Błędy per pole (nazwa pola → klucz i18n); `{}` znaczy „poprawne”. Pierwsza przyczyna wygrywa. */
export function validateForm(
  v: IntegrationFormValues,
  mode: 'create' | 'edit',
): Record<string, string> {
  const result = formSchema(mode).safeParse(v)
  if (result.success) return {}

  const errors: Record<string, string> = {}
  for (const issue of result.error.issues) {
    const field = String(issue.path[0] ?? '')
    if (field !== '' && errors[field] === undefined) errors[field] = issue.message
  }
  return errors
}

export function toCreateBody(
  v: IntegrationFormValues,
): components['schemas']['IntegrationCreateRequest'] {
  return {
    type: 'sharepoint',
    name: v.name.trim(),
    dataset_id: v.dataset_id.trim(),
    tenant_id: v.tenant_id.trim(),
    client_id: v.client_id.trim(),
    client_secret: v.client_secret,
    site_url: v.site_url.trim(),
    excluded_library_names: v.excluded_library_names,
    ignored_extensions: v.ignored_extensions,
    max_file_size_bytes: megabytesToBytes(v.max_file_size_mb),
    scan_interval_seconds: v.scan_interval_seconds,
    delete_propagation: v.delete_propagation,
    is_active: v.is_active,
  }
}

/** Puste `client_secret` przy edycji pomijamy — brak klucza w ciele znaczy „bez zmiany” (§0). */
export function toUpdateBody(
  v: IntegrationFormValues,
): components['schemas']['IntegrationUpdateRequest'] {
  return {
    type: 'sharepoint',
    name: v.name.trim(),
    dataset_id: v.dataset_id.trim(),
    tenant_id: v.tenant_id.trim(),
    client_id: v.client_id.trim(),
    site_url: v.site_url.trim(),
    excluded_library_names: v.excluded_library_names,
    ignored_extensions: v.ignored_extensions,
    max_file_size_bytes: megabytesToBytes(v.max_file_size_mb),
    scan_interval_seconds: v.scan_interval_seconds,
    delete_propagation: v.delete_propagation,
    is_active: v.is_active,
    ...(v.client_secret === '' ? {} : { client_secret: v.client_secret }),
  }
}

export function toTestBody(
  v: IntegrationFormValues,
): components['schemas']['ConnectionTestRequest'] {
  return {
    type: 'sharepoint',
    tenant_id: v.tenant_id.trim(),
    client_id: v.client_id.trim(),
    client_secret: v.client_secret,
    site_url: v.site_url.trim(),
    dataset_id: v.dataset_id.trim(),
    excluded_library_names: v.excluded_library_names,
  }
}

/** Test zapisanej integracji: wszystkie pola, sekret tylko gdy wołający go wpisał. */
export function toSavedTestBody(
  v: IntegrationFormValues,
): components['schemas']['SavedConnectionTestRequest'] {
  return {
    tenant_id: v.tenant_id.trim(),
    client_id: v.client_id.trim(),
    site_url: v.site_url.trim(),
    dataset_id: v.dataset_id.trim(),
    excluded_library_names: v.excluded_library_names,
    ...(v.client_secret === '' ? {} : { client_secret: v.client_secret }),
  }
}
