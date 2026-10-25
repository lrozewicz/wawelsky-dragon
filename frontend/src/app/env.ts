import { z } from 'zod'

import type { FeatureFlags } from '../lib/featureFlags'
import { parseFeatureFlags } from '../lib/featureFlags'

// Klucze konfiguracji runtime — w tej samej kolejności co `serve.ts` (`GET /env-config.js`, kontrakt E0-3 C8).
export const ENV_KEYS = [
  'KEYCLOAK_URL',
  'KEYCLOAK_REALM',
  'KEYCLOAK_CLIENT_ID',
  'DOCS_URL',
  'FEATURE_AGENT',
  'FEATURE_MEMORY',
  'FEATURE_SEARCH',
  'FEATURE_FILES',
] as const

// `serve.ts` emituje wyłącznie stringi, a brak klucza w `__ENV__`/`import.meta.env` znaczy `''`.
export const envSchema: z.ZodObject<{
  KEYCLOAK_URL: z.ZodDefault<z.ZodString>
  KEYCLOAK_REALM: z.ZodDefault<z.ZodString>
  KEYCLOAK_CLIENT_ID: z.ZodDefault<z.ZodString>
  DOCS_URL: z.ZodDefault<z.ZodString>
  FEATURE_AGENT: z.ZodDefault<z.ZodString>
  FEATURE_MEMORY: z.ZodDefault<z.ZodString>
  FEATURE_SEARCH: z.ZodDefault<z.ZodString>
  FEATURE_FILES: z.ZodDefault<z.ZodString>
}> = z.object({
  KEYCLOAK_URL: z.string().default(''),
  KEYCLOAK_REALM: z.string().default(''),
  KEYCLOAK_CLIENT_ID: z.string().default(''),
  DOCS_URL: z.string().default(''),
  FEATURE_AGENT: z.string().default(''),
  FEATURE_MEMORY: z.string().default(''),
  FEATURE_SEARCH: z.string().default(''),
  FEATURE_FILES: z.string().default(''),
})

export type Env = z.infer<typeof envSchema>

declare global {
  interface Window {
    __ENV__?: unknown
  }
}

// `windowEnv` (runtime, z `public/env-config.js` lub `/env-config.js`) ma pierwszeństwo;
// gdy go nie ma, wartości bierzemy z `import.meta.env` pod kluczami `VITE_<KEY>`.
export function readEnv(source?: { windowEnv?: unknown; metaEnv?: Record<string, unknown> }): Env {
  const windowEnv = source?.windowEnv
  let input: unknown
  if (windowEnv === undefined) {
    const metaEnv = source?.metaEnv ?? {}
    const fromMetaEnv: Record<string, unknown> = {}
    for (const key of ENV_KEYS) {
      const value = metaEnv[`VITE_${key}`]
      fromMetaEnv[key] = value === undefined ? '' : value
    }
    input = fromMetaEnv
  } else if (typeof windowEnv === 'object' && windowEnv !== null) {
    input = windowEnv
  } else {
    throw new Error('Nieprawidłowa konfiguracja środowiska: window.__ENV__ nie jest obiektem')
  }
  const result = envSchema.safeParse(input)
  if (!result.success) {
    throw new Error('Nieprawidłowa konfiguracja środowiska: ' + z.prettifyError(result.error))
  }
  return result.data
}

let cachedEnv: Env | undefined

export function getEnv(): Env {
  if (cachedEnv === undefined) {
    cachedEnv = readEnv({ windowEnv: window.__ENV__, metaEnv: import.meta.env })
  }
  return cachedEnv
}

export function resetEnvCache(): void {
  cachedEnv = undefined
}

export function getFeatureFlags(): FeatureFlags {
  return parseFeatureFlags(getEnv())
}
