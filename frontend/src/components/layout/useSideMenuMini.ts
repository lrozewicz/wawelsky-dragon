import { useCallback, useState } from 'react'

// Klucz zapisu stanu zwinięcia; wartość '1' (mini) albo '0' (pełne).
const MINI_STORAGE_KEY = 'wd.sideMenu.mini'

export function useSideMenuMini(autoMini: boolean): { mini: boolean; toggle: () => void } {
  const [stored, setStored] = useState(() => localStorage.getItem(MINI_STORAGE_KEY) === '1')

  const toggle = useCallback(() => {
    setStored((previous) => {
      const next = !previous
      localStorage.setItem(MINI_STORAGE_KEY, next ? '1' : '0')
      return next
    })
  }, [])

  // Wymuszony tryb mini (np. widok pełnoekranowy) wygrywa z zapisanym ustawieniem.
  return { mini: autoMini || stored, toggle }
}
