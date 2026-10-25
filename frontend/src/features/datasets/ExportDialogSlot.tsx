/**
 * Wpięcie dialogu eksportu w pasek zadań (kontekst `<KbTransferHost>`): start → nowy wiersz
 * (`addTask`), 409 `export_in_progress` → podświetlenie istniejącego wiersza (`highlightTask`).
 * Wydzielone z `DatasetsPage.tsx`, które stoi na limicie `max-lines` (eslint, DEC-098).
 */

import { ExportDialog } from '../kb-transfer/ExportDialog'
import { useKbTransfer } from '../kb-transfer/KbTransferHost'

export type ExportDialogSlotProps = {
  dataset: { id: string; name: string }
  onClose: () => void
}

export function ExportDialogSlot(props: ExportDialogSlotProps) {
  const { addTask, highlightTask } = useKbTransfer()
  return (
    <ExportDialog
      dataset={props.dataset}
      onClose={props.onClose}
      onStarted={(ref) => addTask(ref, 'export', props.dataset.name, props.dataset.id)}
      onExisting={highlightTask}
    />
  )
}
