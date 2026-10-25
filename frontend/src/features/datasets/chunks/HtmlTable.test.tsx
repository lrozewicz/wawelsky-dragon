/**
 * Testy `HtmlTable` (kontrakt WP E3-4a §T3): z treści renderują się wyłącznie tagi tabeli,
 * skrypty nie trafiają do DOM-u, a każdy inny element oddaje sam tekst.
 */

import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { HtmlTable } from './HtmlTable'

afterEach(cleanup)

describe('HtmlTable', () => {
  it('renderuje tabelę z komórkami', async () => {
    const { container } = await renderWithProviders(
      <HtmlTable html={'<table><tr><td>A</td></tr></table>'} />,
    )

    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('cell')).toHaveTextContent('A')
    expect(container.querySelectorAll('table')).toHaveLength(1)
  })

  it('nie wstawia skryptu z treści — tabela obok renderuje się normalnie', async () => {
    const { container } = await renderWithProviders(
      <HtmlTable html={'<script>alert(1)</script><table><tr><td>A</td></tr></table>'} />,
    )

    expect(container.querySelector('script')).toBeNull()
    expect(container).not.toHaveTextContent('alert(1)')
    expect(screen.getByRole('cell')).toHaveTextContent('A')
  })

  it('element spoza whitelisty oddaje sam tekst', async () => {
    const { container } = await renderWithProviders(<HtmlTable html={'<div><b>x</b></div>'} />)

    expect(container.querySelector('b')).toBeNull()
    expect(container).toHaveTextContent('x')
  })

  it('obrazek z treści nie trafia do DOM-u, zostaje sam tekst', async () => {
    const { container } = await renderWithProviders(
      <HtmlTable html={'<p>hej <img src="x" onerror="a()"></p>'} />,
    )

    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('p')).toBeNull()
    expect(container).toHaveTextContent('hej')
  })

  it('przenosi rozpiętość komórek jako liczby', async () => {
    const { container } = await renderWithProviders(
      <HtmlTable html={'<table><tr><td colspan="2" rowspan="3">A</td></tr></table>'} />,
    )
    const cell = container.querySelector('td')

    expect(cell).toHaveAttribute('colspan', '2')
    expect(cell).toHaveAttribute('rowspan', '3')
  })

  it('bez tabeli oddaje sam tekst', async () => {
    const { container } = await renderWithProviders(<HtmlTable html={'<p>akapit</p>tekst'} />)

    expect(container.querySelector('p')).toBeNull()
    expect(container).toHaveTextContent('akapittekst')
  })
})
