/** Opisy warunków ręcznego filtra metadanych czatu do chipów nad polem pytania (SC-E67-06 k5). */
import { filterFromWire } from '../../metadata/convert'

/** Np. „typ = raport” (lista wartości → „a, b”); tryby inne niż `manual` nie mają chipów. */
export function filterLabels(raw: Record<string, unknown> | null | undefined): string[] {
  const filter = filterFromWire(raw)
  if (filter.method !== 'manual') return []
  return filter.manual.map(({ key, op, value }) =>
    `${key} ${op} ${Array.isArray(value) ? value.join(', ') : value}`.trim(),
  )
}
