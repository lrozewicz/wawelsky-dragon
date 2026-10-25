export type FileSplit = { accepted: File[]; unreadable: string[] }

// Plik o `size === 0` przeglądarka oddaje bez treści (np. brak dostępu do katalogu) — nazwy
// takich plików trafiają do `unreadable`, reszta do `accepted`; kolejność wejściowa zachowana.
export function splitUnreadable(files: File[]): FileSplit {
  const accepted: File[] = []
  const unreadable: string[] = []
  for (const file of files) {
    if (file.size === 0) unreadable.push(file.name)
    else accepted.push(file)
  }
  return { accepted, unreadable }
}

export type UnreadableSource = 'drop' | 'pick'

const UNREADABLE_KEYS: Record<UnreadableSource, string> = {
  drop: 'common.upload.unreadable.drop',
  pick: 'common.upload.unreadable.pick',
}

/** Klucz i18n (namespace `common`) komunikatu ostrzeżenia dla danego źródła wyboru plików. */
export function unreadableKey(source: UnreadableSource): string {
  return UNREADABLE_KEYS[source]
}

/** Nazwy plików do interpolacji `{{names}}`: join(', '). */
export function formatNames(names: string[]): string {
  return names.join(', ')
}
