/**
 * Podgląd tabeli z treści chunku (kontrakt WP E3-4a §HtmlTable). Treść pochodzi z parsera
 * dokumentów, więc NIE wstrzykujemy jej do DOM-u: parsujemy ją `DOMParser`em (nie wykonuje on
 * skryptów ani nie dociąga zasobów) i budujemy drzewo React wyłącznie z tagów tabelarycznych
 * (whitelista z kontraktu). Każdy inny element oddajemy jako jego tekst, a bez `dangerouslySetInnerHTML`.
 */

import { createElement } from 'react'
import type { JSX, ReactNode } from 'react'
import Box from '@mui/material/Box'

/** Tagi przepuszczane do drzewa React (whitelista z kontraktu). */
const ALLOWED_TAGS = new Set([
  'table',
  'thead',
  'tbody',
  'tfoot',
  'tr',
  'th',
  'td',
  'caption',
  'colgroup',
  'col',
])

/** Tagi, których zawartość nigdy nie jest treścią (kod skryptu/style'u nie trafia do podglądu). */
const SKIPPED_TAGS = new Set(['script', 'style'])

/** Atrybuty przenoszone do React: tylko rozpiętość komórek i tylko jako liczby. */
function spanProps(element: Element): { colSpan?: number; rowSpan?: number } {
  const props: { colSpan?: number; rowSpan?: number } = {}
  for (const [attribute, name] of [
    ['colspan', 'colSpan'],
    ['rowspan', 'rowSpan'],
  ] as const) {
    const value = Number(element.getAttribute(attribute))
    if (Number.isInteger(value) && value > 0) props[name] = value
  }
  return props
}

/** Tekst elementu bez zawartości skryptów i stylów (rekurencyjnie, po węzłach tekstowych). */
function plainText(element: Element): string {
  let text = ''
  element.childNodes.forEach((child) => {
    if (child.nodeType === Node.TEXT_NODE) text += child.textContent ?? ''
    else if (child.nodeType === Node.ELEMENT_NODE) {
      const tag = (child as Element).tagName.toLowerCase()
      if (!SKIPPED_TAGS.has(tag)) text += plainText(child as Element)
    }
  })
  return text
}

/** Buduje węzły: tagi z whitelisty → elementy React, każdy inny element → sam jego tekst. */
function toNodes(nodes: ArrayLike<ChildNode>, keyPrefix: string): ReactNode[] {
  return Array.from(nodes).map((node, index) => {
    const key = `${keyPrefix}.${index}`
    if (node.nodeType === Node.TEXT_NODE) return node.textContent
    if (node.nodeType !== Node.ELEMENT_NODE) return null
    const element = node as Element
    const tag = element.tagName.toLowerCase()
    if (SKIPPED_TAGS.has(tag)) return null
    if (!ALLOWED_TAGS.has(tag)) return plainText(element)
    return createElement(tag, { key, ...spanProps(element) }, toNodes(element.childNodes, key))
  })
}

export function HtmlTable(props: { html: string }): JSX.Element {
  const parsed = new DOMParser().parseFromString(props.html, 'text/html')

  return (
    <Box
      sx={{
        overflowX: 'auto',
        '& table': { borderCollapse: 'collapse', width: '100%' },
        '& th, & td': {
          border: '1px solid',
          borderColor: 'divider',
          px: 1,
          py: 0.5,
          textAlign: 'left',
        },
      }}
    >
      {toNodes(parsed.body.childNodes, 'html')}
    </Box>
  )
}
