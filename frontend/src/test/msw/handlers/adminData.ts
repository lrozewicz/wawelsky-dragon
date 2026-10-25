import type { components } from '../../../api/schema.gen'

// Typy z kontraktu WP E3-6c2 §0 — aliasy schematów WD, bez kopiowania pól.
export type WdUser = components['schemas']['WdUser']
export type ApiKey = components['schemas']['ApiKey']
export type ApiKeyCreated = components['schemas']['ApiKeyCreated']
export type AssistantGrant = components['schemas']['AssistantGrant']
export type Stats = components['schemas']['Stats']
export type AccessReplaceRequest = components['schemas']['AccessReplaceRequest']
export type UserCreateRequest = components['schemas']['UserCreateRequest']
export type UserUpdateRequest = components['schemas']['UserUpdateRequest']

/** Znacznik czasu fixtures (ISO 8601) — stały, żeby testy nie zależały od zegara. */
export const ADMIN_TIMESTAMP = '2025-01-01T00:00:00Z'

/** Stan początkowy handlerów — nadpisywany przez `adminHandlers(seed)` (kontrakt §6). */
export type AdminSeed = {
  users?: WdUser[]
  grants?: Record<string, AssistantGrant[]>
  stats?: Stats
}

export function makeWdUser(overrides: Partial<WdUser> = {}): WdUser {
  return {
    id: 'u-1',
    email: 'jan@wd.test',
    nickname: 'Jan',
    auth_source: 'local',
    is_superuser: false,
    is_active: true,
    language: 'pl',
    timezone: null,
    avatar: null,
    last_login_at: null,
    created_at: ADMIN_TIMESTAMP,
    updated_at: ADMIN_TIMESTAMP,
    ...overrides,
  }
}

export function makeGrant(chatId: string, createdBy: string | null = null): AssistantGrant {
  return { chat_id: chatId, created_by: createdBy, created_at: ADMIN_TIMESTAMP }
}

export function makeStats(overrides: Partial<Stats> = {}): Stats {
  return {
    version: '0.1.0',
    database: { ok: true, elapsed_ms: 3 },
    storage: { ok: true, elapsed_ms: 5 },
    workers: {
      active: 1,
      items: [
        {
          worker_id: 'worker-1',
          version: '0.1.0',
          started_at: ADMIN_TIMESTAMP,
          heartbeat_at: ADMIN_TIMESTAMP,
          active: true,
          capabilities: null,
        },
      ],
    },
    queue: { queued: 0, running: 0, dead: 0 },
    ...overrides,
  }
}

/** Seed domyślny (kontrakt §6): admin@wd.test (superuser) + jan@wd.test. */
export const adminSeed: Required<AdminSeed> = {
  users: [
    makeWdUser({ id: 'u-admin', email: 'admin@wd.test', nickname: 'Admin', is_superuser: true }),
    makeWdUser({ id: 'u-jan', email: 'jan@wd.test', nickname: 'Jan' }),
  ],
  grants: {},
  stats: makeStats(),
}

/** E-mail do porównań: bez otaczających spacji i bez rozróżniania wielkości liter. */
export function normalizeEmail(value: string | null): string {
  return (value ?? '').trim().toLowerCase()
}
