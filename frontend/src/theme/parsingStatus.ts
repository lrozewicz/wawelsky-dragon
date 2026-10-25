import type { Theme } from '@mui/material/styles'

import { gray, green, orange, red } from './themePrimitives'

export type ParsingStatus = 'pending' | 'running' | 'cancel' | 'done' | 'fail'

// Kolory tekstu/ikon statusu parsera plików. Odcienie dobrane tak, by kontrast na
// `background.paper` danego trybu wynosił ≥ 4.5:1 (sprawdza to `contrast.test.ts`):
// light = ciemne odcienie 600, dark = jasne 400 (300 dla czerwieni, której 400 nie
// osiąga progu), `running` = niebieski spoza skal (bez odpowiednika w palecie MUI).
export const parsingStatusColor: Record<ParsingStatus, { light: string; dark: string }> = {
  pending: { light: gray[600], dark: gray[400] },
  running: { light: 'hsl(210, 98%, 42%)', dark: 'hsl(210, 100%, 70%)' },
  cancel: { light: orange[600], dark: orange[400] },
  done: { light: green[600], dark: green[400] },
  fail: { light: red[600], dark: red[300] },
}

/**
 * sx zielonego znacznika „Przesłano” przy pliku w dialogach uploadu (D3, QA E5-H9-1):
 * `success.main` (green[400] w jasnym motywie) miał ~2.4:1 na paperze, token `done` daje
 * pary ≥ 4.5:1 w obu trybach (kontrast: `contrast.test.ts`, opis przy `parsingStatusColor`).
 */
export const doneMarkerColorSx = (theme: Theme) => ({
  color: parsingStatusColor.done.light,
  ...theme.applyStyles('dark', { color: parsingStatusColor.done.dark }),
})
