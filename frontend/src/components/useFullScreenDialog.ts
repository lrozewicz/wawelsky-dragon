/**
 * Czy dialog ma zająć cały ekran (U12, SC-V13-12 k2): poniżej breakpointu `sm` — tak.
 * Wspólny mechanizm długich formularzy (import bazy, eksport bazy, formularz i szczegóły
 * integracji) zamiast kopii `useMediaQuery`; krótkimi dialogami steruje motyw
 * (`MuiDialog` styleOverrides poniżej `sm` w `theme/customizations/feedback.tsx`).
 * `noSsr` jak do dziś w dialogach — bez przeskoków układu po hydratacji.
 */

import useMediaQuery from '@mui/material/useMediaQuery'

export function useFullScreenDialog(): boolean {
  return useMediaQuery((theme) => theme.breakpoints.down('sm'), { noSsr: true })
}
