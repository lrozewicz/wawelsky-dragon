/**
 * Czysta logika formularza instancji dostawcy (kontrakt WP E3-6c1 §3): budowa ciał zapisu
 * i normalizacja adresu bramki. Klucz wysyłamy WYŁĄCZNIE, gdy pole jest niepuste — puste pole
 * znaczy „bez zmiany klucza”, a maska z odczytu (`********`) nigdy nie jedzie jako nowa wartość.
 */

import { z } from 'zod'

import type { components } from '../../../api/schema.gen'
import { MASKED_API_KEY } from '../constants'
import type { ProviderInstanceDetail } from '../providerQueries'

/** Wartości pól formularza instancji (nazwa pola `name` — jak w przykładach briefu). */
export type InstanceFormValues = {
  name: string
  baseUrl: string
  apiKey: string
}

/** Walidacja formularza (zod): nazwa i base URL wymagane, adres musi być `http(s)://`. */
export const instanceFormSchema = z.object({
  name: z.string().trim().min(1, { error: 'settings.instances.nameRequired' }),
  baseUrl: z
    .string()
    .trim()
    .min(1, { error: 'settings.instances.baseUrlRequired' })
    .regex(/^https?:\/\/\S+$/, { error: 'settings.instances.baseUrlInvalid' }),
  apiKey: z.string(),
})

/**
 * Obcina końcowe `/` (kontrakt §3), nie ruszając samego schematu (`http://` zostaje bez zmian).
 * Znak bezpośrednio przed końcowymi ukośnikami nie może być „:” ani „/”.
 */
export function normalizeBaseUrl(url: string): string {
  return url.trim().replace(/(?<=[^:/])\/+$/, '')
}

/**
 * Ciało `POST …/instances`: puste pole klucza pomijamy — klucza nie ma w ciele w ogóle
 * (kontrakt §3). `api_key` jest w schemacie opcjonalne (po E2-H2), więc typ pasuje bez rzutowania.
 */
export function buildInstanceCreate(
  form: InstanceFormValues,
): components['schemas']['ProviderInstanceCreateRequest'] {
  const base = {
    instance_name: form.name.trim(),
    base_url: normalizeBaseUrl(form.baseUrl),
  }
  const apiKey = form.apiKey.trim()
  if (apiKey === '') return base
  return { ...base, api_key: apiKey }
}

/**
 * Ciało `PUT …/instances/{id}`: `api_key` dołączamy tylko, gdy pole niepuste i nie jest maską
 * ani wartością odczytaną z instancji (kontrakt §3).
 */
export function buildInstanceUpdate(
  form: InstanceFormValues,
  detail: ProviderInstanceDetail,
): components['schemas']['ProviderInstanceUpdateRequest'] {
  const base = {
    instance_name: form.name.trim(),
    base_url: normalizeBaseUrl(form.baseUrl),
  }
  const apiKey = form.apiKey.trim()
  if (apiKey === '' || apiKey === MASKED_API_KEY || apiKey === detail.api_key) {
    return base
  }
  return { ...base, api_key: apiKey }
}
