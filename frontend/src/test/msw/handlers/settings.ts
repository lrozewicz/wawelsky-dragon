import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import { apiUrl } from './common'
import {
  DEFAULT_INSTANCE_NAME,
  MASKED_API_KEY,
  MODEL_TYPES,
  SETTINGS_DATE,
  SETTINGS_TIME,
  cloneInstance,
  defaultInstances,
  deriveRegistry,
  findInstance,
  instanceExists,
  isManagedInstance,
  listProviderInstances,
  makeInstanceModel,
  makeRegistryModel,
  makeSeedInstance,
  missingInstanceMessage,
  pathParam,
  providerNameFromPath,
  toApiToken,
  toInstanceDetail,
  toInstanceModel,
  toProvider,
} from './settingsData'
import type {
  ApiToken,
  CreatedApiToken,
  InstanceModelAddRequest,
  InstanceModelUpdateRequest,
  InstanceModelsDeleteRequest,
  ProviderConnectionRequest,
  ProviderInstanceCreateRequest,
  ProviderInstanceUpdateRequest,
  ProviderInstancesDeleteRequest,
  RegistryModel,
  SeedInstance,
  SeedModel,
  SettingsSeed,
  SupportedModel,
} from './settingsData'

// Eksporty wymagane przez kontrakt WP E3-6c1 §6 (fabryki i typy mieszkają w `./settingsData`).
export * from './settingsData'

/**
 * Handlery MSW obszaru settings w kopercie RAGFlow (kontrakt §6): sukces `{code:0,…}`, błędy
 * `{code:101|102,message}` z HTTP 200 (K13 §2). Stan trzymamy w domknięciu tej funkcji — każde
 * wywołanie daje świeży stan, a `server.resetHandlers()` w `src/test/setup.ts` wraca między testami.
 */
export function settingsHandlers(seed: SettingsSeed = {}): HttpHandler[] {
  let tokens: ApiToken[] = (seed.tokens ?? []).map((token) => ({ ...token }))
  let instances: SeedInstance[] = (seed.instances ?? defaultInstances()).map(cloneInstance)
  let registry: RegistryModel[] = (seed.registry ?? deriveRegistry(instances)).map((row) => ({
    ...row,
  }))
  const supported = seed.supported ?? {}
  const connectionResult = seed.connection ?? 'ok'
  let nextInstanceSeq = instances.length + 1
  let nextTokenSeq = tokens.length

  const ok = <T>(data: T) => HttpResponse.json({ code: 0, message: 'success', data })
  const done = () => HttpResponse.json({ code: 0, message: 'success' })
  const argError = (message: string) => HttpResponse.json({ code: 101, message })
  const dataError = (message: string) => HttpResponse.json({ code: 102, message })

  const resolve = (idOrName: string) => findInstance(instances, idOrName)
  const notFound = (request: Request, idOrName: string) =>
    dataError(missingInstanceMessage(providerNameFromPath(request), idOrName))
  const managedError = () =>
    dataError(`Instance '${DEFAULT_INSTANCE_NAME}' is managed by environment configuration`)

  return [
    http.get(apiUrl('/api/v1/system/tokens'), () => ok(tokens)),

    http.post(apiUrl('/api/v1/system/tokens'), ({ request }) => {
      // `?name` — trasa przyjmuje nazwę klucza i odbija ją przyciętą w polu `name`
      // (K20 §1: „echo nazwy po przycięciu; pusta → null”; MINOR V12-1).
      const name = (new URL(request.url).searchParams.get('name') ?? '').trim()
      nextTokenSeq += 1
      const token = `ragflow-${String(nextTokenSeq).padStart(32, '0')}`
      const created: CreatedApiToken = {
        token,
        tenant_id: 'tenant-1',
        name: name || null,
        beta: '0',
        create_time: SETTINGS_TIME,
        create_date: SETTINGS_DATE,
        update_time: null,
        update_date: null,
      }
      tokens = [...tokens, toApiToken(created)]
      return ok(created)
    }),

    http.delete(apiUrl('/api/v1/system/tokens/:token'), ({ params }) => {
      tokens = tokens.filter((token) => token.token !== String(params.token))
      return ok(true)
    }),

    http.get(apiUrl('/api/v1/models'), () => ok(registry)),

    http.get(apiUrl('/api/v1/providers'), () =>
      ok(toProvider(instances, [...new Set(registry.flatMap((row) => row.model_type))])),
    ),

    // ---- Instancje (K13 §3 p. 1–5) ----
    http.get(apiUrl('/api/v1/providers/:name/instances'), () =>
      ok(listProviderInstances(instances)),
    ),

    http.post(apiUrl('/api/v1/providers/:name/instances'), async ({ request }) => {
      const body = (await request.json().catch(() => ({}))) as ProviderInstanceCreateRequest
      const name = (body.instance_name ?? '').trim()
      if (name === '') return argError('instance_name is required')
      if ((body.base_url ?? '') === '') return argError('base_url is required')
      if (instanceExists(instances, name)) return dataError(`Instance '${name}' already exists`)
      const created = makeSeedInstance({
        id: `inst-${nextInstanceSeq}`,
        name,
        base_url: body.base_url,
        api_key: body.api_key ?? '',
        wd_managed: false,
        models: [],
      })
      nextInstanceSeq += 1
      instances = [...instances, created]
      return done()
    }),

    http.get(apiUrl('/api/v1/providers/:name/instances/:instance'), ({ request, params }) => {
      const instance = resolve(String(params.instance))
      return instance === undefined
        ? notFound(request, String(params.instance))
        : ok(toInstanceDetail(instance))
    }),

    http.put(apiUrl('/api/v1/providers/:name/instances/:instance'), async ({ request, params }) => {
      const instance = resolve(String(params.instance))
      if (instance === undefined) return notFound(request, String(params.instance))
      if (isManagedInstance(instance)) return managedError()
      const body = (await request.json().catch(() => ({}))) as ProviderInstanceUpdateRequest
      const missing: string[] = []
      if (!body.instance_name) missing.push('instance_name')
      if (!body.base_url) missing.push('base_url')
      if (missing.length > 0) return argError(`Missing required fields: ${missing.join(', ')}`)
      const name = body.instance_name.trim()
      if (name.toLowerCase() !== instance.name.toLowerCase() && instanceExists(instances, name)) {
        return dataError(`Instance '${name}' already exists`)
      }
      const updated: SeedInstance = { ...instance, name, base_url: body.base_url }
      // `api_key` nieobecny/`null`/maska → bez zmian; `''` → usunięty; inna wartość → nowy (K13 §4 p. 2).
      if (body.api_key === '') updated.api_key = ''
      else if (body.api_key != null && body.api_key !== MASKED_API_KEY)
        updated.api_key = body.api_key
      instances = instances.map((item) => (item.id === updated.id ? updated : item))
      return done()
    }),

    http.delete(apiUrl('/api/v1/providers/:name/instances'), async ({ request }) => {
      const body = (await request.json().catch(() => ({}))) as ProviderInstancesDeleteRequest
      const ids = body.instances ?? []
      if (ids.length === 0) return argError('instances is required')
      const found: SeedInstance[] = []
      for (const idOrName of ids) {
        const instance = resolve(idOrName)
        if (instance === undefined) return notFound(request, idOrName)
        found.push(instance)
      }
      if (found.some(isManagedInstance)) return managedError()
      const removed = new Set(found.map((instance) => instance.id))
      instances = instances.filter((instance) => !removed.has(instance.id))
      registry = registry.filter((row) => !removed.has(row.instance_id))
      return done()
    }),

    http.post(apiUrl('/api/v1/providers/:name/connection'), async ({ request }) => {
      const body = (await request.json().catch(() => ({}))) as ProviderConnectionRequest
      if ((body.base_url ?? '') === '' && (body.instance_id ?? '') === '') {
        return argError('base_url is required')
      }
      if (connectionResult === 'fail') return dataError('Connection failed: HTTP 401')
      return done()
    }),

    // ---- Modele instancji (K13 §3 p. 7–10) ----
    http.get(
      apiUrl('/api/v1/providers/:name/instances/:instance/models'),
      ({ request, params }) => {
        const instance = resolve(String(params.instance))
        if (instance === undefined) return notFound(request, String(params.instance))
        if (new URL(request.url).searchParams.get('supported') === 'true') {
          const items: SupportedModel[] = supported[instance.id] ?? supported[instance.name] ?? []
          return ok(items)
        }
        const models = [...instance.models]
          .sort((a, b) => a.name.localeCompare(b.name))
          .map(toInstanceModel)
        return ok(models)
      },
    ),

    http.post(
      apiUrl('/api/v1/providers/:name/instances/:instance/models'),
      async ({ request, params }) => {
        const instance = resolve(String(params.instance))
        if (instance === undefined) return notFound(request, String(params.instance))
        const body = (await request.json().catch(() => ({}))) as InstanceModelAddRequest
        if (!body.model_name || !body.model_type) {
          return argError('model_name and model_type are required')
        }
        if (!MODEL_TYPES.includes(body.model_type)) {
          return argError(`Invalid model_type '${body.model_type}'`)
        }
        const duplicate = registry.some(
          (row) => row.name === body.model_name && row.model_type.includes(body.model_type),
        )
        if (duplicate) return dataError(`Model '${body.model_name}' already exists`)
        const model = makeInstanceModel({
          name: body.model_name,
          model_type: body.model_type,
          max_tokens: body.max_tokens ?? 8192,
          extra: body.extra ?? {},
          wd_model_id: `model-${body.model_name}`,
          wd_dimension: body.model_type === 'embedding' ? (body.wd_dimension ?? null) : null,
          wd_is_default: false,
        })
        instance.models = [...instance.models, model]
        registry = [...registry, makeRegistryModel(instance, model)]
        return done()
      },
    ),

    // `:modelName*` — nazwa modelu może zawierać `/` (K13 §3 p. 9, `{model_name:path}`).
    http.patch(
      apiUrl('/api/v1/providers/:name/instances/:instance/models/:modelName*'),
      async ({ request, params }) => {
        const instance = resolve(String(params.instance))
        if (instance === undefined) return notFound(request, String(params.instance))
        const body = (await request.json().catch(() => ({}))) as InstanceModelUpdateRequest & {
          model_type?: string
        }
        // Kolejność 101/102 jak w K13 §4 p. 7.
        if (body.status == null && body.max_tokens == null && body.extra == null) {
          return argError('At least one of status, max_tokens, or extra is required.')
        }
        if (body.status != null && body.status !== 'active' && body.status !== 'inactive') {
          return argError("status must be 'active' or 'inactive'")
        }
        if (body.model_type != null) return argError('model_type cannot be changed')
        const modelName = pathParam(params.modelName)
        const model = instance.models.find((item) => item.name === modelName)
        if (model === undefined) return dataError(`Model '${modelName}' not found`)
        if (body.status === 'inactive' && model.wd_is_default) {
          return dataError(`Model '${modelName}' is a default model`)
        }
        if (body.status != null) model.status = body.status
        if (body.max_tokens != null) model.max_tokens = body.max_tokens
        if (body.extra != null) model.extra = body.extra
        return done()
      },
    ),

    http.delete(
      apiUrl('/api/v1/providers/:name/instances/:instance/models'),
      async ({ request, params }) => {
        const instance = resolve(String(params.instance))
        if (instance === undefined) return notFound(request, String(params.instance))
        const body = (await request.json().catch(() => ({}))) as InstanceModelsDeleteRequest
        const names = body.model_name ?? []
        if (names.length === 0) return argError('model_name is required')
        // Wszystko albo nic (K13 §4 p. 3 i 8): najpierw zbierz blokady, dopiero potem usuwaj.
        const found: SeedModel[] = []
        for (const name of names) {
          const model = instance.models.find((item) => item.name === name)
          if (model === undefined) return dataError(`Model '${name}' not found`)
          found.push(model)
        }
        for (const model of found) {
          if (model.wd_is_default) return dataError(`Model '${model.name}' is a default model`)
          const usage = model.used_by_dataset ?? 0
          if (model.model_type === 'embedding' && usage > 0) {
            return dataError(`Model '${model.name}' is used by ${usage} dataset(s)`)
          }
        }
        const removed = new Set(found.map((model) => model.name))
        instance.models = instance.models.filter((model) => !removed.has(model.name))
        registry = registry.filter(
          (row) => !(row.instance_id === instance.id && removed.has(row.name)),
        )
        return done()
      },
    ),
  ]
}
