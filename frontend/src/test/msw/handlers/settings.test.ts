import { describe, expect, it } from 'vitest'

import { server } from '../server'
import { apiUrl } from './common'
import { makeInstanceModel, makeSeedInstance, settingsHandlers } from './settings'
import type { InstanceModel, ProviderInstance, ProviderInstanceDetail } from './settings'

type Envelope<T> = { code: number; message: string; data: T }
type ErrorBody = { code: number; message: string }

const jsonHeaders = { 'Content-Type': 'application/json' }
const PROVIDERS = '/api/v1/providers/litellm'

function post(path: string, body: unknown) {
  return fetch(apiUrl(path), { method: 'POST', headers: jsonHeaders, body: JSON.stringify(body) })
}

describe('handlery MSW — settings (kontrakt WP E3-6c1 §6)', () => {
  it('POST instancji z nazwą `Default` daje 102 „already exists”', async () => {
    server.use(...settingsHandlers())

    const response = await post(`${PROVIDERS}/instances`, {
      instance_name: 'Default',
      base_url: 'http://x/v1',
    })

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({
      code: 102,
      message: "Instance 'Default' already exists",
    })
  })

  it('tworzy instancję (sukces bez `data`) i pokazuje ją na liście za `default`', async () => {
    server.use(...settingsHandlers())

    const created = await post(`${PROVIDERS}/instances`, {
      instance_name: 'moja',
      base_url: 'http://x/v1',
      api_key: 'sk-secret',
    })
    expect(await created.json()).toEqual({ code: 0, message: 'success' })

    const list = (await (await fetch(apiUrl(`${PROVIDERS}/instances`))).json()) as Envelope<
      ProviderInstance[]
    >
    expect(list.code).toBe(0)
    expect(list.data.map((instance) => instance.instance_name)).toEqual(['default', 'moja'])
  })

  it('GET instancji po utworzeniu z kluczem zwraca maskę `********`', async () => {
    server.use(...settingsHandlers())
    await post(`${PROVIDERS}/instances`, {
      instance_name: 'moja',
      base_url: 'http://x/v1',
      api_key: 'sk-secret',
    })

    const body = (await (
      await fetch(apiUrl(`${PROVIDERS}/instances/moja`))
    ).json()) as Envelope<ProviderInstanceDetail>

    expect(body.data.api_key).toBe('********')
    expect(body.data.wd_managed).toBe(false)
  })

  it('PUT bez `api_key` zachowuje klucz (maska), a `api_key: ""` go usuwa', async () => {
    server.use(...settingsHandlers())
    await post(`${PROVIDERS}/instances`, {
      instance_name: 'moja',
      base_url: 'http://x/v1',
      api_key: 'sk-secret',
    })

    await fetch(apiUrl(`${PROVIDERS}/instances/moja`), {
      method: 'PUT',
      headers: jsonHeaders,
      body: JSON.stringify({ instance_name: 'moja', base_url: 'http://y/v1' }),
    })
    const kept = (await (
      await fetch(apiUrl(`${PROVIDERS}/instances/moja`))
    ).json()) as Envelope<ProviderInstanceDetail>
    expect(kept.data.base_url).toBe('http://y/v1')
    expect(kept.data.api_key).toBe('********')

    await fetch(apiUrl(`${PROVIDERS}/instances/moja`), {
      method: 'PUT',
      headers: jsonHeaders,
      body: JSON.stringify({ instance_name: 'moja', base_url: 'http://y/v1', api_key: '' }),
    })
    const cleared = (await (
      await fetch(apiUrl(`${PROVIDERS}/instances/moja`))
    ).json()) as Envelope<ProviderInstanceDetail>
    expect(cleared.data.api_key).toBe('')
  })

  it('edycja instancji `default` daje 102 „managed by environment configuration”', async () => {
    server.use(...settingsHandlers())

    const response = await fetch(apiUrl(`${PROVIDERS}/instances/default`), {
      method: 'PUT',
      headers: jsonHeaders,
      body: JSON.stringify({ instance_name: 'default', base_url: 'http://x/v1' }),
    })

    expect(await response.json()).toEqual({
      code: 102,
      message: "Instance 'default' is managed by environment configuration",
    })
  })

  it('usunięcie modelu domyślnego daje 102', async () => {
    server.use(...settingsHandlers())

    const response = await fetch(apiUrl(`${PROVIDERS}/instances/default/models`), {
      method: 'DELETE',
      headers: jsonHeaders,
      body: JSON.stringify({ model_name: ['fake-llm'] }),
    })

    expect(await response.json()).toEqual({
      code: 102,
      message: "Model 'fake-llm' is a default model",
    })
  })

  it('usunięcie modelu `embedding` w użyciu daje 102 z liczbą datasetów', async () => {
    server.use(
      ...settingsHandlers({
        instances: [
          makeSeedInstance({
            id: 'inst-1',
            name: 'moja',
            models: [
              makeInstanceModel({ name: 'embd-x', model_type: 'embedding', used_by_dataset: 1 }),
            ],
          }),
        ],
      }),
    )

    const response = await fetch(apiUrl(`${PROVIDERS}/instances/inst-1/models`), {
      method: 'DELETE',
      headers: jsonHeaders,
      body: JSON.stringify({ model_name: ['embd-x'] }),
    })

    expect(await response.json()).toEqual({
      code: 102,
      message: "Model 'embd-x' is used by 1 dataset(s)",
    })
  })

  it('POST modelu dodaje go do listy modeli i rejestru', async () => {
    server.use(...settingsHandlers())

    const created = await post(`${PROVIDERS}/instances/default/models`, {
      model_name: 'nova-chat',
      model_type: 'chat',
    })
    expect(await created.json()).toEqual({ code: 0, message: 'success' })

    const models = (await (
      await fetch(apiUrl(`${PROVIDERS}/instances/default/models`))
    ).json()) as Envelope<InstanceModel[]>
    expect(models.data.map((model) => model.name)).toEqual(['fake-embd', 'fake-llm', 'nova-chat'])

    const registry = (await (await fetch(apiUrl('/api/v1/models'))).json()) as Envelope<
      { name: string }[]
    >
    expect(registry.data.map((row) => row.name)).toContain('nova-chat')
  })

  it('PATCH modelu o nazwie z `/` trafia w model instancji', async () => {
    server.use(...settingsHandlers())

    await post(`${PROVIDERS}/instances/default/models`, {
      model_name: 'azure/gpt-4',
      model_type: 'chat',
    })

    const patch = await fetch(apiUrl(`${PROVIDERS}/instances/default/models/azure/gpt-4`), {
      method: 'PATCH',
      headers: jsonHeaders,
      body: JSON.stringify({ status: 'inactive' }),
    })
    expect(await patch.json()).toEqual({ code: 0, message: 'success' })

    const models = (await (
      await fetch(apiUrl(`${PROVIDERS}/instances/default/models`))
    ).json()) as Envelope<InstanceModel[]>
    expect(models.data.find((model) => model.name === 'azure/gpt-4')?.status).toBe('inactive')
  })

  it('tworzy token (`ragflow-` + 32 znaki) i usuwa go', async () => {
    server.use(...settingsHandlers())

    const created = (await (await post('/api/v1/system/tokens?name=CI', {})).json()) as Envelope<{
      token: string
    }>
    expect(created.data.token.startsWith('ragflow-')).toBe(true)
    expect(created.data.token).toHaveLength('ragflow-'.length + 32)

    const list = (await (await fetch(apiUrl('/api/v1/system/tokens'))).json()) as Envelope<
      { token: string }[]
    >
    expect(list.data.map((token) => token.token)).toEqual([created.data.token])

    const removed = (await (
      await fetch(apiUrl(`/api/v1/system/tokens/${created.data.token}`), { method: 'DELETE' })
    ).json()) as Envelope<boolean>
    expect(removed).toEqual({ code: 0, message: 'success', data: true })

    const after = (await (await fetch(apiUrl('/api/v1/system/tokens'))).json()) as Envelope<
      unknown[]
    >
    expect(after.data).toEqual([])
  })

  it('connection wg seeda: domyślnie sukces, `fail` → 102', async () => {
    server.use(...settingsHandlers({ connection: 'fail' }))

    const failed = (await (
      await post(`${PROVIDERS}/connection`, { base_url: 'http://x/v1' })
    ).json()) as ErrorBody
    expect(failed).toEqual({ code: 102, message: 'Connection failed: HTTP 401' })

    server.use(...settingsHandlers())
    const ok = (await (
      await post(`${PROVIDERS}/connection`, { instance_id: 'inst-default' })
    ).json()) as ErrorBody
    expect(ok.code).toBe(0)
  })

  it('`?supported=true` zwraca modele ze seeda', async () => {
    server.use(
      ...settingsHandlers({ supported: { 'inst-default': [{ name: 'gpt-x', rank: 500 }] } }),
    )

    const body = (await (
      await fetch(apiUrl(`${PROVIDERS}/instances/default/models?supported=true`))
    ).json()) as Envelope<{ name: string }[]>

    expect(body.data.map((model) => model.name)).toEqual(['gpt-x'])
  })
})
