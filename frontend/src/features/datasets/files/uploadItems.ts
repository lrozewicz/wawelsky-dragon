/**
 * Pomocnicze operacje na liście plików dialogu uploadu (wydzielone z `UploadDialog.tsx`,
 * limit `max-lines`). Kolejność `uploadFiles` = kolejność przekazanej partii, a partia to
 * podzbiór listy — mapowanie indeksów robi `pendingIndexes`.
 */

import type { UploadItem } from './uploadFiles'

/** Podmiana pól jednego elementu listy po indeksie. */
export function patchItem(
  items: UploadItem[],
  index: number,
  patch: Partial<UploadItem>,
): UploadItem[] {
  return items.map((item, position) => (position === index ? { ...item, ...patch } : item))
}

/** Pozycje listy do wysłania: wszystko poza już przesłanym (SC-E67-04 — bez duplikatów). */
export function pendingIndexes(items: UploadItem[]): number[] {
  return items.flatMap((item, position) => (item.state === 'done' ? [] : [position]))
}

/** Ponowienie: element z błędem wraca do `pending`, jego przyczyna i postęp są czyszczone. */
export function resetForRetry(items: UploadItem[], indexes: number[]): UploadItem[] {
  return items.map((item, position) => {
    if (!indexes.includes(position)) return item
    return { ...item, state: 'pending', loaded: 0, total: 0, error: undefined }
  })
}
