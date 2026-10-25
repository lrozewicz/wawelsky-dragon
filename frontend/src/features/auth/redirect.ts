/**
 * Bezpieczny cel przekierowania po logowaniu (08 §5.3, CONTRACT WP E3-2 §Pliki i nazwy).
 * Wpuszczamy wyłącznie ścieżki wewnętrzne aplikacji: string zaczynający się od `/`, ale nie
 * `//` (adres protokoło-względny `//evil.com`), bez `\` (obejście w rodzaju `/\evil.com`).
 * Wszystko inne — w tym `undefined` z braku parametru — sprowadzamy do `/`.
 */
export function safeRedirect(value: unknown): string {
  if (typeof value !== 'string') return '/'
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return '/'
  return value
}
