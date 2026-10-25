import type { SxProps, Theme } from '@mui/material/styles'

import { red } from '../../../theme/themePrimitives'

/**
 * Styl komunikatu porażki kopiowania (defekt MAJOR z QA-UI E6-2-3): `color="error"` w ciemnym
 * motywie dawał `error.main` = red[500] = rgb(145,8,8) — kontrast 1,44:1 na tle alertu
 * (rgba(59,45,2,0.5)) i ~2:1 na karcie. Jak w `parsingStatus.ts` (`fail`): próg WCAG AA
 * (≥ 4,5:1) na ciemnych tłach osiąga dopiero czerwień 300 (4,97:1 na tle alertu, 5,75:1 na
 * karcie); w jasnym motywie zostaje `error.main` (≥ 5,5:1). Pilnuje test e2e s21 (pomiar
 * `getComputedStyle`).
 */
export const copyErrorSx: SxProps<Theme> = (theme) => ({
  color: 'error.main',
  ...theme.applyStyles('dark', { color: red[300] }),
})
