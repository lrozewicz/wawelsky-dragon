import { vi } from 'vitest'

/**
 * jsdom odpowiada na każde media query `false`, więc wąskie okno (poniżej progu `md`) udajemy
 * atrapą `matchMedia` — `true` dla zapytań `max-width` (wzór: `ChatWorkspacePage.mobile.test.tsx`).
 * Po teście wołający musi wywołać `vi.unstubAllGlobals()`.
 */
export function stubNarrowViewport(): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      get matches() {
        return query.includes('max-width')
      },
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })),
  )
}
