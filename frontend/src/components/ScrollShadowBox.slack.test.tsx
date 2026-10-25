/**
 * Próg nadmiaru przewijania (T15): MUI X wystawia separator ostatniej kolumny 5 px poza treść
 * (`right: -5px`, szerokość 10), więc tabela mieszcząca się w kontenerze ma
 * `scrollWidth` = `clientWidth` + 5 — cień z takiego nadmiaru to fałszywa wskazówka przewijania.
 * Plik osobny od `ScrollShadowBox.test.tsx`, który stoi u limitu 300 linii (eslint max-lines).
 */

import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ScrollShadowBox } from './ScrollShadowBox'

afterEach(cleanup)

/** Podmienia wymiar przewijania elementu (jsdom nie implementuje geometrii układu). */
function mockMetric(element: HTMLElement, name: string, value: number): void {
  Object.defineProperty(element, name, { value, configurable: true })
}

describe('ScrollShadowBox — pomijalny nadmiar przewijania', () => {
  it('nadmiar <= 8 px (separator ostatniej kolumny) nie renderuje cienia; 9 px już tak', () => {
    const { container } = render(
      <ScrollShadowBox>
        <div>treść</div>
      </ScrollShadowBox>,
    )
    const box = container.firstElementChild as HTMLElement
    mockMetric(box, 'scrollWidth', 108)
    mockMetric(box, 'clientWidth', 100)
    mockMetric(box, 'scrollLeft', 0)
    act(() => {
      box.dispatchEvent(new Event('scroll'))
    })
    expect(screen.queryByTestId('scroll-shadow-right')).not.toBeInTheDocument()

    mockMetric(box, 'scrollWidth', 109)
    act(() => {
      box.dispatchEvent(new Event('scroll'))
    })
    expect(screen.getByTestId('scroll-shadow-right')).toBeVisible()
  })
})
