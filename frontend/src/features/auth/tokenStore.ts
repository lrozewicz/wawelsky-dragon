/**
 * Magazyn access tokenu trzymany WYŁĄCZNIE w pamięci modułu (08 §5: brak tokenu w storage —
 * chroni przed XSS). Odświeżanie jest proaktywne: timer ustawiany `REFRESH_LEAD_MS`
 * przed wygaśnięciem `exp` z payloadu JWT.
 */

/** Zapas przed wygaśnięciem tokenu, po którym wołamy callback odświeżający. */
export const REFRESH_LEAD_MS = 60_000

let accessToken: string | null = null
let refreshCallback: (() => Promise<string | null>) | null = null
let refreshTimer: ReturnType<typeof setTimeout> | null = null

/** Dekoduje `exp` (sekundy) z payloadu JWT; token niepoprawny → `null`. */
export function decodeJwtExp(token: string): number | null {
  const segment = token.split('.')[1]
  if (!segment) return null

  try {
    const base64 = segment.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
    const payload = JSON.parse(atob(padded)) as { exp?: unknown }
    return typeof payload.exp === 'number' ? payload.exp : null
  } catch {
    return null
  }
}

export function getAccessToken(): string | null {
  return accessToken
}

function clearRefreshTimer(): void {
  if (refreshTimer !== null) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

function scheduleRefresh(token: string): void {
  const exp = decodeJwtExp(token)
  if (exp === null) return

  const delay = Math.max(0, exp * 1000 - REFRESH_LEAD_MS - Date.now())
  refreshTimer = setTimeout(() => {
    refreshTimer = null
    if (refreshCallback) void refreshCallback()
  }, delay)
}

/** Zapis w pamięci modułu + przeplanowanie proaktywnego odświeżenia; `null` kasuje token i timer. */
export function setAccessToken(token: string | null): void {
  accessToken = token
  clearRefreshTimer()
  if (token !== null) scheduleRefresh(token)
}

export function clearAccessToken(): void {
  setAccessToken(null)
}

export function setRefreshCallback(cb: (() => Promise<string | null>) | null): void {
  refreshCallback = cb
}
