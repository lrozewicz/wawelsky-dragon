/**
 * Pasek zadań eksportu/importu (08 §7.15 (b), CONTRACT WP E7-2 §7): wiersz na zadanie;
 * pusty pasek nie renderuje nic (U5). Podświetlenie (`highlightedId` — po 409
 * `export_in_progress` i po dodaniu wiersza) przewija listę do wiersza; wygaśnięcie
 * podświetlenia pilnuje zegar w `KbTransferHost`.
 */

import { useEffect, useRef } from 'react'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import { useTranslation } from 'react-i18next'

import { isFinishedTask } from './taskStore'
import { TaskRow } from './TaskRow'
import type { StoredKbTask } from './types'

export type TaskBarProps = {
  tasks: StoredKbTask[]
  highlightedId: string | null
  onRemove: (taskId: string) => void
  onClearFinished: () => void
}

/** Jak długo (w `KbTransferHost`) podświetlenie wiersza pozostaje widoczne. */
export const KB_HIGHLIGHT_MS = 3000

export function TaskBar(props: TaskBarProps) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement | null>(null)

  // Po zmianie podświetlenia (także po dodaniu wiersza) przewijamy pasek, by wiersz był widoczny.
  useEffect(() => {
    if (props.highlightedId === null) return
    containerRef.current
      ?.querySelector(`[data-task-id="${CSS.escape(props.highlightedId)}"]`)
      ?.scrollIntoView?.({ block: 'nearest' })
  }, [props.highlightedId, props.tasks])

  if (props.tasks.length === 0) return null
  return (
    <Stack ref={containerRef} spacing={1} data-testid="kb-task-bar" sx={{ mb: 2 }}>
      {props.tasks.some((row) => isFinishedTask(row.last)) ? (
        <Button
          size="small"
          data-testid="kb-clear-finished"
          onClick={props.onClearFinished}
          sx={{ alignSelf: 'flex-end', whiteSpace: 'nowrap' }}
        >
          {t('kbTransfer.tasks.clearFinished')}
        </Button>
      ) : null}
      {props.tasks.map((row) => (
        <TaskRow
          key={row.task_id}
          row={row}
          highlighted={row.task_id === props.highlightedId}
          onRemove={props.onRemove}
        />
      ))}
    </Stack>
  )
}
