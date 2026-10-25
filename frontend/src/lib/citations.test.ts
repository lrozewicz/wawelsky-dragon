import { describe, expect, it } from 'vitest'

import { tokenizeCitations, type CitationSegment } from './citations'

// Odtwarza tekst z segmentów: znacznik składamy z powrotem z indeksu (kontrakt §4).
function joined(segments: CitationSegment[]): string {
  return segments.map((s) => (s.type === 'text' ? s.text : `[ID:${s.index}]`)).join('')
}

describe('tokenizeCitations', () => {
  it('zamienia znaczniki w prozie na segmenty cytowań', () => {
    expect(tokenizeCitations('a [ID:0] b [ID:1].', 2)).toEqual([
      { type: 'text', text: 'a ' },
      { type: 'citation', index: 0 },
      { type: 'text', text: ' b ' },
      { type: 'citation', index: 1 },
      { type: 'text', text: '.' },
    ])
  })

  it('pomija znacznik poza zakresem chunków i scala sąsiedni tekst', () => {
    expect(tokenizeCitations('x [ID:5] y', 2)).toEqual([{ type: 'text', text: 'x  y' }])
  })

  it('zostawia znacznik w kodzie inline `…` jako tekst', () => {
    expect(tokenizeCitations('`[ID:0]`', 1)).toEqual([{ type: 'text', text: '`[ID:0]`' }])
  })

  it('zostawia znacznik w bloku kodu ``` … ``` jako tekst', () => {
    expect(tokenizeCitations('```\n[ID:0]\n```', 1)).toEqual([
      { type: 'text', text: '```\n[ID:0]\n```' },
    ])
    // Backtick inline wewnątrz bloku nie domyka bloku.
    expect(tokenizeCitations('```\n`[ID:0]\n```', 1)).toEqual([
      { type: 'text', text: '```\n`[ID:0]\n```' },
    ])
  })

  it('tokenizuje prozę wokół kodu, kod przechodzi bez zmian', () => {
    const segments = tokenizeCitations('a `[ID:0]` b [ID:1]', 2)
    expect(segments).toEqual([
      { type: 'text', text: 'a `[ID:0]` b ' },
      { type: 'citation', index: 1 },
    ])
    expect(joined(segments)).toBe('a `[ID:0]` b [ID:1]')
  })

  it('niezamknięty blok kodu traktuje resztę tekstu jako kod', () => {
    expect(tokenizeCitations('proza [ID:0]\n```\n[ID:0]', 1)).toEqual([
      { type: 'text', text: 'proza ' },
      { type: 'citation', index: 0 },
      { type: 'text', text: '\n```\n[ID:0]' },
    ])
  })

  it('pusty tekst daje pustą listę', () => {
    expect(tokenizeCitations('', 0)).toEqual([])
  })

  it('sam znacznik daje tylko segment cytowania', () => {
    expect(tokenizeCitations('[ID:0]', 1)).toEqual([{ type: 'citation', index: 0 }])
  })
})
