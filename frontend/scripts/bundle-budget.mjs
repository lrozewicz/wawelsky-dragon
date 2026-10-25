// Budżet początkowego JS (kontrakt WP E3-7 §C4): czyta manifest Vite (`build.manifest`, dodane
// w `vite.config.ts`) i sumuje rozmiar gzip plików wejścia oraz jego statycznych importów.
// Bez zależności — czysty Node ESM, uruchamiany jako `node scripts/bundle-budget.mjs`.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { gzipSync } from 'node:zlib'

/** Limit budżetu początkowego JS w kB (kontrakt §C4). */
export const LIMIT_KB = 350
const DIST_DIR = 'dist'
const MANIFEST_PATH = join(DIST_DIR, '.vite', 'manifest.json')

/**
 * Zbiera posortowane ścieżki plików `.js` chunku wejściowego (`isEntry`) i jego statycznych
 * `imports` (rekurencyjnie, bez `dynamicImports`). Cykl importów nie zapętla — klucze manifestu
 * odwiedzamy raz.
 */
export function collectInitialFiles(manifest) {
  const files = new Set()
  const visited = new Set()
  const visit = (key) => {
    if (visited.has(key)) return
    visited.add(key)
    const chunk = manifest[key]
    if (!chunk) return
    if (typeof chunk.file === 'string' && chunk.file.endsWith('.js')) files.add(chunk.file)
    for (const imported of chunk.imports ?? []) visit(imported)
  }
  for (const [key, chunk] of Object.entries(manifest)) {
    if (chunk.isEntry) visit(key)
  }
  return [...files].sort()
}

/** Rozmiar pliku po gzipie (poziom 9) w kB dziesiętnych — jak Vite liczy `kB`. */
function gzipKb(relativePath) {
  return gzipSync(readFileSync(join(DIST_DIR, relativePath)), { level: 9 }).length / 1000
}

function main() {
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'))
  const totalKb = collectInitialFiles(manifest).reduce((sum, file) => sum + gzipKb(file), 0)
  console.log(`bundle-budget: ${totalKb.toFixed(1)} kB gzip (limit ${LIMIT_KB} kB)`)
  if (totalKb > LIMIT_KB) process.exitCode = 1
}

// `main()` tylko przy bezpośrednim uruchomieniu (`bun run bundle-budget`) — import w teście
// vitest nie może czytać `dist/`.
if (process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main()
}
