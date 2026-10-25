import { describe, expect, it } from 'vitest'

import { splitThink } from './splitThink'

describe('splitThink', () => {
  it('rozdziela domknięty blok think od odpowiedzi', () => {
    expect(splitThink('<think>a</think>b')).toEqual({ thinking: 'a', answer: 'b' })
  })

  it('trymuje thinking i pomija whitespace wokół bloku', () => {
    expect(splitThink('  <think> a </think>\n\n b')).toEqual({ thinking: 'a', answer: 'b' })
  })

  it('zwraca cały tekst jako answer, gdy nie ma bloku think', () => {
    expect(splitThink('zwykły')).toEqual({ thinking: '', answer: 'zwykły' })
  })

  it('traktuje niedomknięty think jako trwające myślenie', () => {
    expect(splitThink('<think>abc')).toEqual({ thinking: 'abc', answer: '' })
  })

  it('trymuje myślenie z niedomkniętego bloku z wcięciem', () => {
    expect(splitThink('  <think> abc ')).toEqual({ thinking: 'abc', answer: '' })
  })

  it('nie rozpoznaje think, gdy nie jest na początku tekstu', () => {
    expect(splitThink('x <think>a</think>')).toEqual({ thinking: '', answer: 'x <think>a</think>' })
  })

  it('zachowuje wieloliniowe thinking i answer', () => {
    expect(splitThink('<think>linia1\nlinia2</think>\nodpowiedź\nwieloliniowa')).toEqual({
      thinking: 'linia1\nlinia2',
      answer: 'odpowiedź\nwieloliniowa',
    })
  })

  it('obsługuje pusty blok think', () => {
    expect(splitThink('<think></think>')).toEqual({ thinking: '', answer: '' })
  })

  it('obsługuje pusty tekst', () => {
    expect(splitThink('')).toEqual({ thinking: '', answer: '' })
  })
})
