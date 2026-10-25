// Pomocnik axe (kontrakt WP E3-7 §C5): jedno wywołanie na głównym ekranie scenariusza S6.
// Każde wywołanie loguje `axe-check: <context>` przez `console.log` (nie `console.error` —
// strażnik konsoli w `../fixtures.ts` traktuje błędy jako porażkę testu); liczbę sprawdzeń
// zlicza się z wyjścia e2e.
import AxeBuilder from '@axe-core/playwright'
import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

// Reguły wyłączone na stałe. Pusta lista świadomie — każde wyłączenie wymaga decyzji (DEC-220…223).
const DISABLED_RULES: string[] = []

/** Tagi WCAG objęte sprawdzeniem (kontrakt §C5). */
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

/** Skrót naruszenia: `id (impact): target1; target2` — po jednym targecie na węzeł. */
function formatViolation(violation: {
  id: string
  impact?: string | null
  nodes: { target: (string | string[])[] }[]
}): string {
  const targets = violation.nodes.map((node) => node.target.join(' ')).join('; ')
  return `${violation.id} (${violation.impact}): ${targets}`
}

/**
 * Analizuje stronę axe'em i wymaga braku naruszeń o wpływie `critical`/`serious`
 * w tagach WCAG z `TAGS`. `context` opisuje ekran (trafia do komunikatu i logu).
 */
export async function expectNoSeriousA11y(page: Page, context: string): Promise<void> {
  console.log('axe-check: ' + context)
  const results = await new AxeBuilder({ page })
    .withTags(TAGS)
    .disableRules(DISABLED_RULES)
    .analyze()
  const violations = results.violations
    .filter((violation) => violation.impact === 'critical' || violation.impact === 'serious')
    .map(formatViolation)
  expect(violations, context + ': ' + violations.join(' | ')).toEqual([])
}
