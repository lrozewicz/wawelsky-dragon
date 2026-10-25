/**
 * Komórka kolumny „Status” zakładki Pliki (kontrakt WP E3-3b §T2). Stan bierze wyłącznie
 * z `parsingState`/`progressPercent`, więc jedyne źródło prawdy o `run` zostaje w T1a:
 * idle → ▶, queued → zegar + „W kolejce” + ⊗, running → pasek postępu + procent + ⊗,
 * done/failed/cancelled → chip + ↻. Hover i focus komórki otwierają popover z początkiem,
 * czasem trwania i ostatnimi liniami `progress_msg`; klik w tekst statusu woła `onOpenLog`.
 *
 * Podpowiedź to `Popper`, nie `Popover`: MUI `Popover` opiera się na `Modal`, którego `ModalManager`
 * nadaje `aria-hidden="true"` całej reszcie strony — przyciski ▶/⊗/↻ komórki trafiałyby do
 * ukrytego poddrzewa. `Popper` jest niemodalny (bez `aria-hidden` i bez przechwytywania
 * wskaźnika), dodatkowo `pointerEvents: 'none'`, żeby paper nie zabierał zdarzeń myszy komórce.
 */

import { useState } from 'react'
import type { JSX, KeyboardEvent, MouseEvent, FocusEvent, ReactNode } from 'react'
import CancelIcon from '@mui/icons-material/Cancel'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import ReplayIcon from '@mui/icons-material/Replay'
import ScheduleIcon from '@mui/icons-material/Schedule'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import type { ChipProps } from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import LinearProgress from '@mui/material/LinearProgress'
import Paper from '@mui/material/Paper'
import Popper from '@mui/material/Popper'
import Stack from '@mui/material/Stack'
import { useTheme } from '@mui/material/styles'
import Typography from '@mui/material/Typography'
import { useTranslation } from 'react-i18next'

import { resolveLanguage } from '../../../i18n'
import { formatDateTime } from '../../../lib/format'
import { translateProgressLog } from '../../../lib/serverMessages'
import { parsingState, progressPercent } from './parsingState'
import type { ParsingState } from './parsingState'
import type { DocumentRow } from './queries'

/** Pola wiersza, których potrzebuje komórka (kontrakt §T2). */
export type ParsingStatusDoc = Pick<
  DocumentRow,
  | 'id'
  | 'name'
  | 'run'
  | 'progress'
  | 'chunk_count'
  | 'process_begin_at'
  | 'process_duration'
  | 'progress_msg'
>

export type ParsingStatusCellProps = {
  doc: ParsingStatusDoc
  /** ▶ (idle) i ↻ (done/failed/cancelled). */
  onParse: (doc: ParsingStatusDoc) => void
  /** ⊗ (running/queued). */
  onStop: (doc: ParsingStatusDoc) => void
  /** Klik w tekst statusu — otwiera dialog logu (T7). */
  onOpenLog: (doc: ParsingStatusDoc) => void
}

/** Ile ostatnich niepustych linii `progress_msg` pokazuje popover (kontrakt §T2). */
const LOG_LINES = 5

/** Kolory chipa dla stanów końcowych (kontrakt §T2). */
const CHIP_COLORS: Partial<Record<ParsingState, ChipProps['color']>> = {
  done: 'success',
  failed: 'error',
  cancelled: 'default',
}

/** Ostatnie niepuste linie logu albo `null`, gdy log jest pusty. */
function lastLogLines(message: string): string | null {
  const lines = message.split('\n').filter((line) => line !== '')
  if (lines.length === 0) return null
  return lines.slice(-LOG_LINES).join('\n')
}

/** Tekst statusu jest przyciskiem — klik otwiera dialog logu parsowania. */
function StatusText(props: {
  testId: string
  onClick: () => void
  children: ReactNode
}): JSX.Element {
  return (
    <Box
      component="button"
      type="button"
      data-testid={props.testId}
      onClick={props.onClick}
      sx={{
        border: 0,
        bgcolor: 'transparent',
        p: 0,
        font: 'inherit',
        color: 'inherit',
        cursor: 'pointer',
        textAlign: 'left',
        whiteSpace: 'nowrap',
      }}
    >
      {props.children}
    </Box>
  )
}

export function ParsingStatusCell(props: ParsingStatusCellProps): JSX.Element {
  const { doc, onParse, onStop, onOpenLog } = props
  const { t, i18n } = useTranslation()
  const language = resolveLanguage(i18n.language)
  const theme = useTheme()
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)

  const state = parsingState(doc)
  const percent = progressPercent(doc.progress)
  const parseTestId = `status-parse-${doc.id}`
  const stopTestId = `status-stop-${doc.id}`
  const logTestId = `status-log-${doc.id}`
  const popoverId = `status-popover-${doc.id}`

  function openPopover(event: MouseEvent<HTMLDivElement> | FocusEvent<HTMLDivElement>): void {
    setAnchorEl(event.currentTarget)
  }

  function closePopover(): void {
    setAnchorEl(null)
  }

  // Focus (focusout) bąbelkuje z dzieci; przejście fokusu w obrębie komórki jej nie zamyka.
  function handleBlur(event: FocusEvent<HTMLDivElement>): void {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return
    setAnchorEl(null)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Escape') setAnchorEl(null)
  }

  // Ostatnie linie logu tłumaczone przy wyświetleniu (T3b, K20 §5 p. 4) — zmiana języka
  // tłumaczy też już wyrenderowany popover.
  const log = lastLogLines(doc.progress_msg)
  const translatedLog = log === null ? null : translateProgressLog(log, t)

  return (
    <Box
      data-testid={`status-cell-${doc.id}`}
      aria-describedby={anchorEl === null ? undefined : popoverId}
      onMouseEnter={openPopover}
      onMouseLeave={closePopover}
      onFocus={openPopover}
      onBlur={handleBlur}
      onKeyDown={handleKeyDown}
      sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}
    >
      {state === 'idle' ? (
        <IconButton
          size="small"
          aria-label={t('datasets.files.status.parse')}
          data-testid={parseTestId}
          onClick={() => onParse(doc)}
        >
          <PlayArrowIcon fontSize="small" />
        </IconButton>
      ) : null}

      {state === 'queued' ? <ScheduleIcon fontSize="small" color="action" /> : null}

      {state === 'running' ? (
        <LinearProgress
          variant="determinate"
          value={percent}
          aria-label={t('datasets.files.status.progress')}
          // 52 px (nie 72) — komórka statusu mieści się w kolumnie 165 px przy 1280 px (T7).
          sx={{ width: 52 }}
        />
      ) : null}

      {state === 'queued' || state === 'running' ? (
        <>
          <StatusText testId={logTestId} onClick={() => onOpenLog(doc)}>
            {state === 'queued' ? t('datasets.files.status.queued') : `${percent}%`}
          </StatusText>
          <IconButton
            size="small"
            aria-label={t('datasets.files.status.stop')}
            data-testid={stopTestId}
            onClick={() => onStop(doc)}
          >
            <CancelIcon fontSize="small" />
          </IconButton>
        </>
      ) : null}

      {state === 'done' || state === 'failed' || state === 'cancelled' ? (
        <>
          <Chip
            size="small"
            color={CHIP_COLORS[state]}
            label={t(`datasets.files.status.${state}`)}
            data-testid={logTestId}
            onClick={() => onOpenLog(doc)}
          />
          <IconButton
            size="small"
            aria-label={t('datasets.files.status.reparse')}
            data-testid={parseTestId}
            onClick={() => onParse(doc)}
          >
            <ReplayIcon fontSize="small" />
          </IconButton>
        </>
      ) : null}

      <Popper
        id={popoverId}
        role="tooltip"
        open={anchorEl !== null}
        anchorEl={anchorEl}
        placement="bottom-start"
        sx={{ pointerEvents: 'none', zIndex: theme.zIndex.tooltip }}
      >
        <Paper sx={{ p: 2, maxWidth: 360 }}>
          <Stack spacing={0.5}>
            <Typography variant="caption" color="text.secondary">
              {t('datasets.files.popover.begin')}
            </Typography>
            <Typography variant="body2">
              {doc.process_begin_at === null ? '—' : formatDateTime(doc.process_begin_at, language)}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('datasets.files.popover.duration')}
            </Typography>
            <Typography variant="body2">{`${Math.round(doc.process_duration)} s`}</Typography>
            <Typography variant="caption" color="text.secondary">
              {t('datasets.files.popover.log')}
            </Typography>
            <Box
              component="pre"
              sx={{
                m: 0,
                maxHeight: 160,
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
                fontFamily: 'monospace',
                fontSize: 12,
              }}
            >
              {translatedLog ?? t('datasets.files.popover.noLog')}
            </Box>
          </Stack>
        </Paper>
      </Popper>
    </Box>
  )
}
