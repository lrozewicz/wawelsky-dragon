// Fixture'y e2e (kontrakt WP E3-2 §„Pliki i nazwy"): konto z seedu K9, automatyczny strażnik
// błędów konsoli oraz pomocnik ponownego resetu bazy.
import { test as base, expect } from '@playwright/test'
import type { APIRequestContext, ConsoleMessage } from '@playwright/test'
import { collectLayoutDefects, withoutKnownDefects } from './helpers/layout'

export const ADMIN_EMAIL = 'admin@wd.test'
export const ADMIN_PASSWORD = 'wd-test-admin-1'

const API_URL = process.env.WD_E2E_API_URL ?? ''

// Strażnik wad układu na końcu każdego testu (helpers/layout.ts, analiza 2026-10-09):
// strict — wada oblewa test; warn — adnotacja `layout-defect` w raporcie; off — wyłączony.
const LAYOUT_GUARD = process.env.WD_E2E_LAYOUT_GUARD ?? 'strict'

// 401 z `/api/v1/auth/refresh` to oczekiwany stan „brak sesji" (08 §5.3) — Chromium loguje go
// jako błąd konsoli tylko dlatego, że żądanie sieciowe zwróciło status błędu. Filtr po adresie
// zasobu: błąd aplikacji logowany z tym samym tekstem ma adres modułu, nie endpointu.
function isExpectedRefresh401(message: ConsoleMessage): boolean {
  return message.text().includes('401') && message.location().url.includes('/api/v1/auth/refresh')
}

export const test = base.extend<{}>({
  page: async ({ page }, use) => {
    const errors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error' && !isExpectedRefresh401(message)) {
        errors.push(`${message.text()} (${message.location().url})`)
      }
    })
    page.on('pageerror', (error) => {
      errors.push(`pageerror: ${error.message}`)
    })

    await use(page)

    expect(errors, 'błędy konsoli/pageerror w trakcie testu').toEqual([])

    if (LAYOUT_GUARD !== 'off' && !page.isClosed() && page.url().startsWith('http')) {
      const defects = withoutKnownDefects(
        (await collectLayoutDefects(page)).map((d) => `${d.kind}: ${d.detail}`),
      )
      if (LAYOUT_GUARD === 'warn') {
        for (const defect of defects) {
          test.info().annotations.push({ type: 'layout-defect', description: defect })
        }
      } else {
        expect(defects, 'wady układu na końcowym ekranie testu (helpers/layout.ts)').toEqual([])
      }
    }
  },
})

export { expect }

/** Ponowny reset danych stosu (`POST /api/wd/v1/test/reset`) — dla scenariuszy zależnych od seedu. */
export async function resetDb(request: APIRequestContext): Promise<void> {
  const response = await request.post(`${API_URL}/api/wd/v1/test/reset`, { data: {} })
  if (response.status() !== 200) {
    throw new Error(`test/reset ${response.status()}: ${await response.text()}`)
  }
}
