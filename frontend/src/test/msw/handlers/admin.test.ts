import { describe, expect, it } from 'vitest'

import { server } from '../server'
import { adminHandlers, adminSeed, makeGrant } from './admin'
import { apiUrl } from './common'

// Neutralna wartość testowa markera auto-provisioningu; sufiks rozpoznaje `isAutoProvisioned`
// z `features/admin/constants.ts` (kontrakt §0, DEC-312).
const AUTO_PROVISIONED_BY = 'hub-compat-auto-provisioning'

type UsersPageBody = {
  data: { items: { email: string }[]; total: number; page: number; page_size: number }
}
type ErrorBody = { error: { code: string; message: string } }

const jsonHeaders = { 'Content-Type': 'application/json' }

describe('handlery MSW — admin (kontrakt WP E3-6c2 §6)', () => {
  it('GET /api/wd/v1/users filtruje po q i stronicuje domyślnym page_size=25', async () => {
    const response = await fetch(apiUrl('/api/wd/v1/users?q=jan'))

    expect(response.status).toBe(200)
    const body = (await response.json()) as UsersPageBody
    expect(body.data.total).toBe(1)
    expect(body.data.page).toBe(1)
    expect(body.data.page_size).toBe(25)
    expect(body.data.items.map((user) => user.email)).toEqual(['jan@wd.test'])
  })

  it('GET /api/wd/v1/users bez q zwraca cały seed', async () => {
    const response = await fetch(apiUrl('/api/wd/v1/users'))

    const body = (await response.json()) as UsersPageBody
    expect(body.data.total).toBe(2)
    expect(body.data.items.map((user) => user.email)).toEqual(['admin@wd.test', 'jan@wd.test'])
  })

  it('POST /api/wd/v1/users z zajętym e-mailem daje 409 conflict', async () => {
    const response = await fetch(apiUrl('/api/wd/v1/users'), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ email: 'jan@wd.test', is_superuser: false }),
    })

    expect(response.status).toBe(409)
    const body = (await response.json()) as ErrorBody
    expect(body.error.code).toBe('conflict')
    expect(body.error.message).not.toBe('')
  })

  it('POST /api/wd/v1/users zakłada konto (201) i dopisuje je do listy', async () => {
    server.use(...adminHandlers())

    const response = await fetch(apiUrl('/api/wd/v1/users'), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ email: 'nowy@wd.test', nickname: 'Nowy', is_superuser: false }),
    })

    expect(response.status).toBe(201)
    const body = (await response.json()) as { data: { id: string; email: string } }
    expect(body.data.email).toBe('nowy@wd.test')

    const list = (await (
      await fetch(apiUrl('/api/wd/v1/users?q=nowy@wd.test'))
    ).json()) as UsersPageBody
    expect(list.data.total).toBe(1)
  })

  it('PATCH degradujący jedynego administratora daje 409 conflict', async () => {
    server.use(...adminHandlers())
    const adminId = adminSeed.users.find((user) => user.is_superuser)?.id ?? ''

    const response = await fetch(apiUrl(`/api/wd/v1/users/${adminId}`), {
      method: 'PATCH',
      headers: jsonHeaders,
      body: JSON.stringify({ is_superuser: false }),
    })

    expect(response.status).toBe(409)
    const body = (await response.json()) as ErrorBody
    expect(body.error.code).toBe('conflict')
  })

  it('POST api-keys zwraca token, a GET api-keys go nie zawiera', async () => {
    server.use(...adminHandlers())

    const created = await fetch(apiUrl('/api/wd/v1/users/u-jan/api-keys'), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ name: 'CI' }),
    })

    expect(created.status).toBe(201)
    const createdBody = (await created.json()) as {
      data: { name: string | null; prefix: string; token: string }
    }
    expect(createdBody.data.name).toBe('CI')
    expect(createdBody.data.token.startsWith('wdk-')).toBe(true)
    expect(createdBody.data.prefix).toBe(createdBody.data.token.slice(0, 16))

    const list = await fetch(apiUrl('/api/wd/v1/users/u-jan/api-keys'))
    expect(list.status).toBe(200)
    const listBody = (await list.json()) as { data: { items: Record<string, unknown>[] } }
    expect(listBody.data.items).toHaveLength(1)
    expect(listBody.data.items[0]).not.toHaveProperty('token')
  })

  it('PUT access/assistants podmienia granty, zostawiając grant automatyczny', async () => {
    server.use(
      ...adminHandlers({
        grants: {
          'jan@wd.test': [makeGrant('c1', AUTO_PROVISIONED_BY), makeGrant('c3', 'admin@wd.test')],
        },
      }),
    )

    const response = await fetch(apiUrl('/api/wd/v1/access/assistants'), {
      method: 'PUT',
      headers: jsonHeaders,
      body: JSON.stringify({ email: 'jan@wd.test', chat_ids: ['c2'] }),
    })
    expect(response.status).toBe(200)

    const after = await fetch(apiUrl('/api/wd/v1/access/assistants?email=jan@wd.test'))
    const body = (await after.json()) as { data: { items: { chat_id: string }[] } }
    expect(body.data.items.map((grant) => grant.chat_id).sort()).toEqual(['c1', 'c2'])
  })
})
