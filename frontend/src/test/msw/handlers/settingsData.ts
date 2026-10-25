import type { components } from '../../../api/schema.gen'

// Typy z kontraktu WP E3-6c1 §0 i §6 — aliasy schematów WD (nie z `features/settings`, którego jeszcze nie ma).
export type ApiToken = components['schemas']['ApiToken']
export type CreatedApiToken = components['schemas']['CreatedApiToken']
export type Provider = components['schemas']['Provider']
export type ProviderInstance = components['schemas']['ProviderInstance']
export type ProviderInstanceDetail = components['schemas']['ProviderInstanceDetail']
export type InstanceModel = components['schemas']['InstanceModel']
export type SupportedModel = components['schemas']['SupportedModel']
export type RegistryModel = components['schemas']['Model']
export type ProviderInstanceCreateRequest = components['schemas']['ProviderInstanceCreateRequest']
export type ProviderInstanceUpdateRequest = components['schemas']['ProviderInstanceUpdateRequest']
export type ProviderConnectionRequest = components['schemas']['ProviderConnectionRequest']
export type InstanceModelAddRequest = components['schemas']['InstanceModelAddRequest']
export type InstanceModelUpdateRequest = components['schemas']['InstanceModelUpdateRequest']
export type InstanceModelsDeleteRequest = components['schemas']['InstanceModelsDeleteRequest']
export type ProviderInstancesDeleteRequest = components['schemas']['ProviderInstancesDeleteRequest']

/** Nazwa instancji domyślnej (środowiskowej) — zastrzeżona, tylko do odczytu (K13 §0 p. 2). */
export const DEFAULT_INSTANCE_NAME = 'default'
export const DEFAULT_INSTANCE_ID = 'inst-default'
export const DEFAULT_INSTANCE_BASE_URL = 'http://gateway.test/v1'

/** Identyfikator dostawcy w odpowiedziach atrapy (K13 §0 p. 3: v1 = `litellm`). */
export const PROVIDER_ID = 'litellm'
/** Maskowana wartość klucza API (kontrakt §1: `MASKED_API_KEY`). */
export const MASKED_API_KEY = '********'
/** Typy modelu (K13 §2) — wejście i wyjście API. */
export const MODEL_TYPES = ['chat', 'embedding', 'rerank', 'vision']

/** Znacznik czasu fixtures — stały, żeby testy nie zależały od zegara. */
export const SETTINGS_TIME = 1735689600 // 2025-01-01 00:00:00 UTC (sekundy)
export const SETTINGS_DATE = '2025-01-01T00:00:00Z'

/**
 * Model seeda: schemat `InstanceModel` plus flaga użycia `used_by_dataset` (kontrakt §6) —
 * używana wyłącznie w handlerze DELETE do blokady modelu `embedding` (K13 §4 p. 8).
 */
export type SeedModel = InstanceModel & { used_by_dataset?: number }

export type SeedInstance = {
  id: string
  name: string
  base_url: string
  api_key: string
  wd_managed: boolean
  models: SeedModel[]
}

/** Stan początkowy handlerów — nadpisywany przez `settingsHandlers(seed)` (kontrakt §6). */
export type SettingsSeed = {
  tokens?: ApiToken[]
  instances?: SeedInstance[]
  supported?: Record<string, SupportedModel[]>
  connection?: 'ok' | 'fail'
  registry?: RegistryModel[]
}

export function makeToken(overrides: Partial<ApiToken> = {}): ApiToken {
  return {
    token: 'ragflow-00000000000000000000000000000001',
    tenant_id: 'tenant-1',
    name: null,
    dialog_id: null,
    source: null,
    beta: '0',
    create_time: SETTINGS_TIME,
    create_date: SETTINGS_DATE,
    update_time: SETTINGS_TIME,
    update_date: SETTINGS_DATE,
    ...overrides,
  }
}

export function makeInstanceModel(overrides: Partial<SeedModel> = {}): SeedModel {
  return {
    name: 'fake-llm',
    model_type: 'chat',
    max_tokens: 8192,
    status: 'active',
    rank: 500,
    extra: {},
    wd_model_id: 'model-fake-llm',
    wd_dimension: null,
    wd_is_default: false,
    ...overrides,
  }
}

export function makeSeedInstance(overrides: Partial<SeedInstance> = {}): SeedInstance {
  return {
    id: 'inst-1',
    name: 'litellm-test',
    base_url: 'http://gateway.test/v1',
    api_key: '',
    wd_managed: false,
    models: [],
    ...overrides,
  }
}

/** Wiersz rejestru (`GET /api/v1/models`) wyliczony z instancji i jej modeli (kontrakt §6). */
export function makeRegistryModel(instance: SeedInstance, model: SeedModel): RegistryModel {
  return {
    model_id: model.wd_model_id,
    tenant_id: 'tenant-1',
    tenant_name: 'wawelsky',
    model_type: [model.model_type],
    name: model.name,
    provider_id: PROVIDER_ID,
    provider_name: 'OpenAI-API-Compatible',
    instance_id: instance.id,
    instance_name: instance.name,
    rank: model.rank,
  }
}

export function deriveRegistry(instances: SeedInstance[]): RegistryModel[] {
  return instances.flatMap((instance) =>
    instance.models.map((model) => makeRegistryModel(instance, model)),
  )
}

/** Domyślne instancje (kontrakt §6): instancja `default` z modelami `fake-llm` i `fake-embd`. */
export function defaultInstances(): SeedInstance[] {
  return [
    makeSeedInstance({
      id: DEFAULT_INSTANCE_ID,
      name: DEFAULT_INSTANCE_NAME,
      base_url: DEFAULT_INSTANCE_BASE_URL,
      wd_managed: true,
      models: [
        makeInstanceModel({
          name: 'fake-llm',
          model_type: 'chat',
          wd_model_id: 'model-fake-llm',
          wd_is_default: true,
        }),
        makeInstanceModel({
          name: 'fake-embd',
          model_type: 'embedding',
          wd_model_id: 'model-fake-embd',
          wd_dimension: 8,
          wd_is_default: true,
        }),
      ],
    }),
  ]
}

// ---- Pomocnicze widoki i komunikaty (koperta i reguły 101/102 z K13 §2 i §4) ----

/** Kopia instancji z klonami modeli — stan handlerów nie dzieli referencji z seedem. */
export function cloneInstance(instance: SeedInstance): SeedInstance {
  return { ...instance, models: instance.models.map((model) => ({ ...model })) }
}

/** Instancja `default` (środowiskowa): `wd_managed` albo nazwa `default` (bez wielkości liter). */
export function isManagedInstance(instance: SeedInstance): boolean {
  return instance.wd_managed || instance.name.toLowerCase() === DEFAULT_INSTANCE_NAME
}

/** `{instance}` = id albo nazwa; nazwa dopasowana też bez rozróżniania wielkości liter (K13 §0 p. 2). */
export function findInstance(
  instances: SeedInstance[],
  idOrName: string,
): SeedInstance | undefined {
  return (
    instances.find((instance) => instance.id === idOrName) ??
    instances.find((instance) => instance.name === idOrName) ??
    instances.find((instance) => instance.name.toLowerCase() === idOrName.toLowerCase())
  )
}

export function instanceExists(instances: SeedInstance[], name: string): boolean {
  return instances.some((instance) => instance.name.toLowerCase() === name.toLowerCase())
}

/** Nazwa dostawcy ze ścieżki `/api/v1/providers/{name}/…`. */
export function providerNameFromPath(request: Request): string {
  return new URL(request.url).pathname.split('/')[4] ?? PROVIDER_ID
}

export function missingInstanceMessage(provider: string, idOrName: string): string {
  return `No instance found for provider '${provider}' and instance '${idOrName}'`
}

/** `:model_name` może zawierać `/` — MSW oddaje wtedy tablicę segmentów (patrz PATCH). */
export function pathParam(value: string | readonly string[] | undefined): string {
  const raw = typeof value === 'string' ? value : (value ?? []).join('/')
  return decodeURIComponent(raw)
}

export function toApiToken(created: CreatedApiToken): ApiToken {
  return {
    token: created.token,
    tenant_id: created.tenant_id,
    name: created.name,
    dialog_id: null,
    source: null,
    beta: created.beta,
    create_time: created.create_time,
    create_date: created.create_date,
    update_time: SETTINGS_TIME,
    update_date: SETTINGS_DATE,
  }
}

/** Odpowiedź modelu bez flagi seeda `used_by_dataset` (nie ma jej w schemacie `InstanceModel`). */
export function toInstanceModel(model: SeedModel): InstanceModel {
  return {
    name: model.name,
    model_type: model.model_type,
    max_tokens: model.max_tokens,
    status: model.status,
    rank: model.rank,
    extra: model.extra,
    wd_model_id: model.wd_model_id,
    wd_dimension: model.wd_dimension ?? null,
    wd_is_default: model.wd_is_default,
  }
}

export function toProviderInstance(instance: SeedInstance): ProviderInstance {
  return {
    id: instance.id,
    instance_name: instance.name,
    provider_id: PROVIDER_ID,
    region: 'default',
    status: 'active',
  }
}

export function toInstanceDetail(instance: SeedInstance): ProviderInstanceDetail {
  return {
    id: instance.id,
    instance_name: instance.name,
    provider_id: PROVIDER_ID,
    region: 'default',
    base_url: instance.base_url,
    // Klucz nigdy nie wraca plaintextem (K13 §0 p. 5) — tylko `''` albo stała maska.
    api_key: instance.api_key === '' ? '' : MASKED_API_KEY,
    status: 'active',
    wd_managed: isManagedInstance(instance),
  }
}

/** Instancja `default` pierwsza, reszta w kolejności utworzenia (K13 §3 p. 1). */
export function listProviderInstances(instances: SeedInstance[]): ProviderInstance[] {
  return [...instances]
    .sort((a, b) => Number(isManagedInstance(b)) - Number(isManagedInstance(a)))
    .map(toProviderInstance)
}

export function toProvider(instances: SeedInstance[], modelTypes: string[]): Provider {
  return {
    name: PROVIDER_ID,
    url: { default: instances[0]?.base_url ?? DEFAULT_INSTANCE_BASE_URL },
    has_instance: instances.length > 0,
    model_types: modelTypes,
  }
}
