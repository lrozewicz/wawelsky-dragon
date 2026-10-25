/**
 * Wspólny strażnik niezapisanych zmian szuflad (SC-V12-07): każda ścieżka zamknięcia (Esc,
 * klik w tło, „Anuluj”, ✕ w nagłówku) przy brudnym formularzu otwiera dialog „Odrzucić
 * zmiany?”, a przy czystym zamyka szufladę od razu. Zapis woła bezpośrednio `onClose` —
 * bez pytania. Hook zwraca `requestClose` do podpięcia pod wszystkie ścieżki zamknięcia
 * oraz `dialog` do wyrenderowania obok szuflady. Użycia: `ChatSettingsDrawer`,
 * `SearchSettingsDrawer` (zastąpił własny confirm), `MetadataDrawer`.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'

import { DiscardChangesDialog } from './DiscardChangesDialog'
import type { DiscardContext } from './DiscardChangesDialog'

export type UseDiscardGuardOptions = {
  /** `true`, gdy wartości formularza są inne niż początkowe (ustala wywołujący, per szuflada). */
  dirty: boolean
  /** Zamknięcie szuflady — przez „Odrzuć” albo bezpośrednio przy czystym formularzu. */
  onClose: () => void
  /** Nazwa kontekstu w treści dialogu („…w ustawieniach czatu…”). */
  context: DiscardContext
  /** Stan otwarcia szuflady: zamknięcie gasi otwarte pytanie (U7 — ponowne otwarcie od zera). */
  open: boolean
}

export function useDiscardGuard(options: UseDiscardGuardOptions): {
  requestClose: () => void
  dialog: ReactNode
} {
  const { dirty, onClose, context, open } = options
  const [confirmOpen, setConfirmOpen] = useState(false)

  // Szuflada zamknięta z zewnątrz (np. po zapisie albo nawigacja rodzica) — pytanie nie może
  // przeżyć do ponownego otwarcia. Korekta stanu podczas renderu przy zmianie propsa `open`
  // (wzorzec: `SearchSettingsDrawer`), bez efektu.
  const [lastOpen, setLastOpen] = useState(open)
  if (lastOpen !== open) {
    setLastOpen(open)
    if (!open) setConfirmOpen(false)
  }

  function requestClose(): void {
    if (dirty) {
      setConfirmOpen(true)
      return
    }
    onClose()
  }

  const dialog = (
    <DiscardChangesDialog
      open={confirmOpen}
      context={context}
      onKeep={() => setConfirmOpen(false)}
      onDiscard={() => {
        setConfirmOpen(false)
        onClose()
      }}
    />
  )
  return { requestClose, dialog }
}
