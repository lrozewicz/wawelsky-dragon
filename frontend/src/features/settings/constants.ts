/**
 * Stałe sekcji Ustawień (kontrakt WP E3-6c1 §1): dostawca w ścieżkach, typy modeli,
 * maska klucza API i nazwa instancji zarządzanej przez środowisko.
 */

/** Dostawca w ścieżkach `/providers/{name}/…` (kontrakt §0) — jedyny obsługiwany w WD. */
export const PROVIDER = 'litellm'

/** Typy modeli przyjmowane i zwracane przez API (kontrakt §0). */
export const MODEL_TYPES = ['chat', 'embedding', 'rerank', 'vision'] as const

export type ModelType = (typeof MODEL_TYPES)[number]

/** Maska klucza API zwracana przez backend w `ProviderInstanceDetail.api_key`. */
export const MASKED_API_KEY = '********'

/** Instancja z konfiguracji środowiska — tylko do odczytu (kontrakt §0). */
export const DEFAULT_INSTANCE_NAME = 'default'

/** Przedrostek tokenu klucza API; w masce widoczny jest jego początek. */
export const TOKEN_LEAD = 'ragflow-'
