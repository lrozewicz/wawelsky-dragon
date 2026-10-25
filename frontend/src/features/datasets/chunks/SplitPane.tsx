/**
 * Dwupanelowy układ strony chunków (08 §7.5, kontrakt WP E3-4a §SplitPane): lewy panel ma
 * `leftPercent`% szerokości kontenera (start 40), prawy resztę, a między nimi jest przeciągalny
 * dzielnik (`role="separator"`). Dzielnik łapie wskaźnik przez `setPointerCapture`, więc procent
 * liczymy z `getBoundingClientRect` kontenera i trzymamy w zakresie 20–70; klawiatura ←/→ zmienia
 * go o 5 p.p. Poniżej progu `md` panele układają się w kolumnę i dzielnik znika (`useMediaQuery`).
 */

import { useRef, useState } from 'react'
import type { JSX, KeyboardEvent, PointerEvent, ReactNode } from 'react'
import Box from '@mui/material/Box'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useTranslation } from 'react-i18next'

/** Domyślna szerokość lewego panelu w procentach (kontrakt §SplitPane). */
export const SPLIT_DEFAULT_PERCENT = 40
/** Granice szerokości lewego panelu (kontrakt §SplitPane). */
export const SPLIT_MIN_PERCENT = 20
export const SPLIT_MAX_PERCENT = 70
/** Krok klawiatury w punktach procentowych (kontrakt §SplitPane). */
export const SPLIT_KEY_STEP = 5

export type SplitPaneProps = {
  left: ReactNode
  right: ReactNode
  initialLeftPercent?: number
}

function clamp(value: number): number {
  return Math.min(SPLIT_MAX_PERCENT, Math.max(SPLIT_MIN_PERCENT, value))
}

export function SplitPane(props: SplitPaneProps): JSX.Element {
  const { left, right, initialLeftPercent = SPLIT_DEFAULT_PERCENT } = props
  const { t } = useTranslation()
  const belowMd = useMediaQuery((theme) => theme.breakpoints.down('md'), { noSsr: true })
  const [percent, setPercent] = useState(clamp(initialLeftPercent))
  const container = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  /** Procent z pozycji wskaźnika względem kontenera; bez zmierzonej szerokości zostaje bieżący. */
  function percentAt(clientX: number): number {
    const rect = container.current?.getBoundingClientRect()
    if (rect === undefined || rect.width === 0) return percent
    return clamp(((clientX - rect.left) / rect.width) * 100)
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>): void {
    dragging.current = true
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>): void {
    if (!dragging.current) return
    setPercent(percentAt(event.clientX))
  }

  function handlePointerUp(event: PointerEvent<HTMLDivElement>): void {
    if (!dragging.current) return
    dragging.current = false
    event.currentTarget.releasePointerCapture(event.pointerId)
  }

  /**
   * Przerwanie przeciągania (np. gest systemowy) — przeglądarka sama zwalnia przechwycenie,
   * więc tylko kończymy tryb; bez tego kolejny ruch wskaźnika nad dzielnikiem przesuwałby go.
   */
  function handlePointerCancel(): void {
    dragging.current = false
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      setPercent((current) => clamp(current - SPLIT_KEY_STEP))
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      setPercent((current) => clamp(current + SPLIT_KEY_STEP))
    }
  }

  return (
    <Box
      ref={container}
      sx={{
        display: 'flex',
        flexDirection: belowMd ? 'column' : 'row',
        gap: 2,
        flex: 1,
        minWidth: 0,
        minHeight: 0,
      }}
    >
      <Box sx={{ width: belowMd ? '100%' : `${String(percent)}%`, minWidth: 0 }}>{left}</Box>
      {belowMd ? null : (
        <Box
          role="separator"
          tabIndex={0}
          data-testid="chunks-split-separator"
          aria-orientation="vertical"
          aria-label={t('chunks.split.label')}
          aria-valuenow={Math.round(percent)}
          aria-valuemin={SPLIT_MIN_PERCENT}
          aria-valuemax={SPLIT_MAX_PERCENT}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerCancel}
          onKeyDown={handleKeyDown}
          sx={{
            flexShrink: 0,
            width: 8,
            cursor: 'col-resize',
            borderRadius: 1,
            bgcolor: 'divider',
            touchAction: 'none',
          }}
        />
      )}
      <Box sx={{ flex: 1, minWidth: 0 }}>{right}</Box>
    </Box>
  )
}
