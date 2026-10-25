import { describe, expect, it } from 'vitest'

import { isPlainLeftClick } from './linkClick'
import type { ClickEventLike } from './linkClick'

/** Zdarzenie bazowe: lewy przycisk, bez modyfikatorów, nieobsłużone — „zwykły” klik. */
const plain: ClickEventLike = {
  button: 0,
  ctrlKey: false,
  metaKey: false,
  shiftKey: false,
  altKey: false,
  defaultPrevented: false,
}

describe('isPlainLeftClick', () => {
  const cases: { name: string; event: ClickEventLike; expected: boolean }[] = [
    { name: 'lewy przycisk bez modyfikatorów', event: plain, expected: true },
    { name: 'środkowy przycisk (button 1)', event: { ...plain, button: 1 }, expected: false },
    { name: 'prawy przycisk (button 2)', event: { ...plain, button: 2 }, expected: false },
    { name: 'ctrl (nowa karta)', event: { ...plain, ctrlKey: true }, expected: false },
    { name: 'meta (cmd)', event: { ...plain, metaKey: true }, expected: false },
    { name: 'shift (nowe okno)', event: { ...plain, shiftKey: true }, expected: false },
    { name: 'alt (pobranie)', event: { ...plain, altKey: true }, expected: false },
    {
      name: 'zdarzenie już obsłużone (defaultPrevented)',
      event: { ...plain, defaultPrevented: true },
      expected: false,
    },
  ]

  for (const { name, event, expected } of cases) {
    it(`${expected ? 'przyjmuje' : 'odrzuca'}: ${name}`, () => {
      expect(isPlainLeftClick(event)).toBe(expected)
    })
  }
})
