import { HttpResponse, http } from 'msw'
import type { HttpHandler } from 'msw'

import { isAutoProvisioned } from '../../../features/admin/constants'
import { ADMIN_TIMESTAMP, adminSeed, makeGrant, makeWdUser, normalizeEmail } from './adminData'
import type {
  AccessReplaceRequest,
  AdminSeed,
  ApiKey,
  ApiKeyCreated,
  AssistantGrant,
  UserCreateRequest,
  UserUpdateRequest,
  WdUser,
} from './adminData'
import { apiUrl } from './common'

// Eksporty wymagane przez kontrakt WP E3-6c2 §6 (fabryki i seed mieszkają w `./adminData`).
export { adminSeed, makeGrant, makeStats, makeWdUser } from './adminData'

/** Domyślny rozmiar strony listy użytkowników (kontrakt §6: `page_size` = 25). */
const DEFAULT_PAGE_SIZE = 25
const MAX_PAGE_SIZE = 100

function positiveInt(value: string | null, fallback: number): number {
  const parsed = Number.parseInt(value ?? '', 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function cloneGrants(source: Record<string, AssistantGrant[]>): Record<string, AssistantGrant[]> {
  return Object.fromEntries(
    Object.entries(source).map(([email, grants]) => [email, grants.map((grant) => ({ ...grant }))]),
  )
}

/** Wartownik zwracany przez `parseExpiresAt`, gdy data jest niepoprawna (odróżnia go od `null`). */
const INVALID_EXPIRY = Symbol('invalid-expiry')

/**
 * Normalizuje `expires_at` z ciała (K14 §3 p. 1): brak/`null` → `null` (klucz bezterminowy),
 * poprawna data ISO **ze strefą** i w przyszłości → ISO UTC, inaczej `INVALID_EXPIRY`.
 */
function parseExpiresAt(value: string | null | undefined): string | null | typeof INVALID_EXPIRY {
  if (value === null || value === undefined) return null
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) return INVALID_EXPIRY
  const at = new Date(value).getTime()
  if (!Number.isFinite(at) || at <= Date.now()) return INVALID_EXPIRY
  return new Date(at).toISOString()
}

/** Lista kluczy nie zawiera tokenu (kontrakt §0) — świadomie przepisujemy same pola. */
function toApiKey(created: ApiKeyCreated): ApiKey {
  return {
    id: created.id,
    name: created.name,
    prefix: created.prefix,
    created_at: created.created_at,
    last_used_at: created.last_used_at,
    expires_at: created.expires_at,
  }
}

/**
 * Handlery obszaru admin w kopercie wd (kontrakt §0 i §6): sukces `{data}`, 204 bez ciała,
 * błąd `{error:{code,message}}`. Każde wywołanie daje świeży stan, a `server.resetHandlers()`
 * w `src/test/setup.ts` wraca do seedu domyślnego między testami.
 */
export function adminHandlers(seed: AdminSeed = {}): HttpHandler[] {
  let users = (seed.users ?? adminSeed.users).map((user) => ({ ...user }))
  const grants = cloneGrants(seed.grants ?? adminSeed.grants)
  const stats = { ...(seed.stats ?? adminSeed.stats) }
  const keysByUser: Record<string, ApiKey[]> = {}
  let nextUserId = users.length + 1
  let nextKeySeq = 1

  const findUser = (id: string) => users.find((user) => user.id === id)
  const otherActiveSuperusers = (id: string) =>
    users.filter((user) => user.id !== id && user.is_superuser && user.is_active).length

  const conflict = (message: string) =>
    HttpResponse.json({ error: { code: 'conflict', message } }, { status: 409 })
  const notFound = (message: string) =>
    HttpResponse.json({ error: { code: 'not_found', message } }, { status: 404 })

  // Straż ostatniego administratora: degradacja/usunięcie ostatniego aktywnego superusera → 409.
  const guardsLastAdmin = (user: WdUser) =>
    user.is_superuser && user.is_active && otherActiveSuperusers(user.id) === 0

  const replaceUser = (updated: WdUser) => {
    users = users.map((user) => (user.id === updated.id ? updated : user))
    return updated
  }

  return [
    http.get(apiUrl('/api/wd/v1/users'), ({ request }) => {
      const search = new URL(request.url).searchParams
      const page = positiveInt(search.get('page'), 1)
      const pageSize = Math.min(
        positiveInt(search.get('page_size'), DEFAULT_PAGE_SIZE),
        MAX_PAGE_SIZE,
      )
      const query = (search.get('q') ?? '').trim().toLowerCase()
      const email = normalizeEmail(search.get('email'))
      const matched = users.filter((user) => {
        if (email !== '') return normalizeEmail(user.email) === email
        if (query === '') return true
        return (
          user.email.toLowerCase().includes(query) || user.nickname.toLowerCase().includes(query)
        )
      })
      const start = (page - 1) * pageSize
      return HttpResponse.json({
        data: {
          items: matched.slice(start, start + pageSize),
          total: matched.length,
          page,
          page_size: pageSize,
        },
      })
    }),

    http.post(apiUrl('/api/wd/v1/users'), async ({ request }) => {
      const body = (await request.json()) as UserCreateRequest
      const email = body.email.trim()
      if (users.some((user) => normalizeEmail(user.email) === normalizeEmail(email))) {
        return conflict(`Account with e-mail ${email} already exists`)
      }
      const created = makeWdUser({
        id: `u-${nextUserId}`,
        email,
        nickname: body.nickname ?? email.split('@')[0] ?? '',
        is_superuser: body.is_superuser,
      })
      nextUserId += 1
      users = [...users, created]
      return HttpResponse.json({ data: created }, { status: 201 })
    }),

    http.get(apiUrl('/api/wd/v1/users/:userId'), ({ params }) => {
      const user = findUser(String(params.userId))
      return user === undefined ? notFound('User not found') : HttpResponse.json({ data: user })
    }),

    http.patch(apiUrl('/api/wd/v1/users/:userId'), async ({ request, params }) => {
      const user = findUser(String(params.userId))
      if (user === undefined) return notFound('User not found')
      const body = (await request.json()) as UserUpdateRequest
      const losesAdmin =
        user.is_superuser &&
        user.is_active &&
        (body.is_superuser === false || body.is_active === false)
      if (losesAdmin && guardsLastAdmin(user)) {
        return conflict('Cannot demote or deactivate the last administrator')
      }
      // Brak pola (albo `null`) oznacza brak zmiany — `WdUser` nie zna `null` w tych polach.
      const updated: WdUser = { ...user }
      if (body.nickname != null) updated.nickname = body.nickname
      if (body.is_superuser != null) updated.is_superuser = body.is_superuser
      if (body.is_active != null) updated.is_active = body.is_active
      return HttpResponse.json({ data: replaceUser(updated) })
    }),

    http.delete(apiUrl('/api/wd/v1/users/:userId'), ({ params }) => {
      const user = findUser(String(params.userId))
      if (user === undefined) return notFound('User not found')
      if (guardsLastAdmin(user)) return conflict('Cannot delete the last administrator')
      users = users.filter((item) => item.id !== user.id)
      return new HttpResponse(null, { status: 204 })
    }),

    http.post(apiUrl('/api/wd/v1/users/:userId/password'), async ({ request, params }) => {
      const user = findUser(String(params.userId))
      if (user === undefined) return notFound('User not found')
      if (user.auth_source !== 'local') {
        return conflict('Password can only be set for local accounts')
      }
      await request.json().catch(() => ({}))
      return new HttpResponse(null, { status: 204 })
    }),

    http.post(apiUrl('/api/wd/v1/users/:userId/activate'), ({ params }) => {
      const user = findUser(String(params.userId))
      if (user === undefined) return notFound('User not found')
      return HttpResponse.json({ data: replaceUser({ ...user, is_active: true }) })
    }),

    http.post(apiUrl('/api/wd/v1/users/:userId/deactivate'), ({ params }) => {
      const user = findUser(String(params.userId))
      if (user === undefined) return notFound('User not found')
      if (guardsLastAdmin(user)) return conflict('Cannot deactivate the last administrator')
      return HttpResponse.json({ data: replaceUser({ ...user, is_active: false }) })
    }),

    http.get(apiUrl('/api/wd/v1/users/:userId/api-keys'), ({ params }) => {
      const user = findUser(String(params.userId))
      if (user === undefined) return notFound('User not found')
      return HttpResponse.json({ data: { items: keysByUser[user.id] ?? [] } })
    }),

    http.post(apiUrl('/api/wd/v1/users/:userId/api-keys'), async ({ request, params }) => {
      const user = findUser(String(params.userId))
      if (user === undefined) return notFound('User not found')
      const body = (await request.json().catch(() => ({}))) as {
        name?: string | null
        expires_at?: string | null
      }
      // K14 §3 p. 1: data bez strefy, nieparsowalna albo `<= now` → 400 i klucz nie powstaje.
      const expiresAt = parseExpiresAt(body.expires_at)
      if (expiresAt === INVALID_EXPIRY) {
        return HttpResponse.json(
          {
            error: {
              code: 'validation_failed',
              message: 'expires_at must be an ISO 8601 date in the future with a timezone',
            },
          },
          { status: 400 },
        )
      }
      const seq = String(nextKeySeq).padStart(12, '0')
      nextKeySeq += 1
      // `prefix` = pierwsze 16 znaków tokenu (kontrakt §0), token jawny tylko w tej odpowiedzi.
      const prefix = `wdk-${seq}`
      const created: ApiKeyCreated = {
        id: `key-${seq}`,
        name: body.name ?? null,
        prefix,
        created_at: ADMIN_TIMESTAMP,
        last_used_at: null,
        expires_at: expiresAt,
        token: `${prefix}-secret`,
      }
      keysByUser[user.id] = [...(keysByUser[user.id] ?? []), toApiKey(created)]
      return HttpResponse.json({ data: created }, { status: 201 })
    }),

    http.delete(apiUrl('/api/wd/v1/users/:userId/api-keys/:keyId'), ({ params }) => {
      const user = findUser(String(params.userId))
      if (user === undefined) return notFound('User not found')
      const keys = keysByUser[user.id] ?? []
      if (!keys.some((key) => key.id === params.keyId)) return notFound('API key not found')
      keysByUser[user.id] = keys.filter((key) => key.id !== params.keyId)
      return new HttpResponse(null, { status: 204 })
    }),

    http.get(apiUrl('/api/wd/v1/access/assistants'), ({ request }) => {
      const email = normalizeEmail(new URL(request.url).searchParams.get('email'))
      return HttpResponse.json({ data: { items: email === '' ? [] : (grants[email] ?? []) } })
    }),

    http.put(apiUrl('/api/wd/v1/access/assistants'), async ({ request }) => {
      const body = (await request.json()) as AccessReplaceRequest
      const email = normalizeEmail(body.email)
      const auto = (grants[email] ?? []).filter((grant) => isAutoProvisioned(grant.created_by))
      const autoChatIds = new Set(auto.map((grant) => grant.chat_id))
      const manual = [...new Set(body.chat_ids)]
        .filter((chatId) => !autoChatIds.has(chatId))
        .map((chatId) => makeGrant(chatId))
      const replaced = [...auto, ...manual]
      grants[email] = replaced
      return HttpResponse.json({ data: { email, count: replaced.length } })
    }),

    http.get(apiUrl('/api/wd/v1/stats'), () => HttpResponse.json({ data: stats })),

    // Surowe ciało bez koperty (kontrakt §0) — `/api/v1/system/healthz`.
    http.get(apiUrl('/api/v1/system/healthz'), () =>
      HttpResponse.json({
        db: 'ok',
        doc_engine: 'ok',
        redis: 'ok',
        status: 'ok',
        storage: 'ok',
      }),
    ),
  ]
}
