import { useCallback, useState } from 'react'

// Klucz zapisu stanu zwinięcia; wartość '1' (mini) albo '0' (pełne).
const MINI_STORAGE_KEY = 'wd.sideMenu.mini'

export function useSideMenuMini(autoMini: boolean): { mini: boolean; toggle: () => void } {
  const [stored, setStored] = useState(() => localStorage.getItem(MINI_STORAGE_KEY) === '1')
  // Widok pełnoekranowy (np. czat) startuje zwinięty, ale użytkownik może rozwinąć menu.
  // Ten wybór nie trafia do zapisu: nie zmienia układu pozostałych stron.
  const [autoExpanded, setAutoExpanded] = useState(false)

  const toggle = useCallback(() => {
    if (autoMini) {
      setAutoExpanded((previous) => !previous)
      return
    }
    setStored((previous) => {
      const next = !previous
      localStorage.setItem(MINI_STORAGE_KEY, next ? '1' : '0')
      return next
    })
  }, [autoMini])

  return { mini: autoMini ? !autoExpanded : stored, toggle }
}
