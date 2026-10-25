export type FeatureFlags = {
  agent: boolean
  memory: boolean
  search: boolean
  files: boolean
}

const FLAG_KEYS = {
  agent: 'FEATURE_AGENT',
  memory: 'FEATURE_MEMORY',
  search: 'FEATURE_SEARCH',
  files: 'FEATURE_FILES',
} as const

function isFlagEnabled(env: Record<string, unknown>, key: string): boolean {
  const value = env[key]
  return value === true || value === 'true' || value === '1'
}

export function parseFeatureFlags(env: Record<string, unknown>): FeatureFlags {
  return {
    agent: isFlagEnabled(env, FLAG_KEYS.agent),
    memory: isFlagEnabled(env, FLAG_KEYS.memory),
    search: isFlagEnabled(env, FLAG_KEYS.search),
    files: isFlagEnabled(env, FLAG_KEYS.files),
  }
}
