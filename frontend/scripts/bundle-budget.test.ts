// Testy `collectInitialFiles` (kontrakt WP E3-7 §C4, brief T3 pkt 3). Skryptu `main()` nie
// uruchamiamy — import modułu nie czyta `dist/`.
import { describe, expect, it } from 'vitest'
import { collectInitialFiles } from './bundle-budget.mjs'

describe('collectInitialFiles', () => {
  it('zbiera pliki wejścia i statycznych importów, pomija dynamicImports', () => {
    const manifest = {
      'index.html': { file: 'a.js', isEntry: true, imports: ['_v'], dynamicImports: ['x'] },
      _v: { file: 'v.js' },
      x: { file: 'x.js' },
    }
    expect(collectInitialFiles(manifest)).toEqual(['a.js', 'v.js'])
  })

  it('nie zapętla się na cyklu importów', () => {
    const manifest = {
      'index.html': { file: 'a.js', isEntry: true, imports: ['b'] },
      b: { file: 'b.js', imports: ['a'] },
      a: { file: 'a.js', imports: ['b'] },
    }
    expect(collectInitialFiles(manifest)).toEqual(['a.js', 'b.js'])
  })

  it('pomija pliki inne niż .js', () => {
    const manifest = {
      'index.html': { file: 'index.js', isEntry: true, imports: ['css'] },
      css: { file: 'style.css' },
    }
    expect(collectInitialFiles(manifest)).toEqual(['index.js'])
  })
})
