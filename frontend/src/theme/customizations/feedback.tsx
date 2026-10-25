// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/shared-theme/customizations/feedback.tsx (MIT). Zmiany: importy typów (type Theme, type Components), usunięty nieaktywny komentarz eslint-disable, formatowanie Prettier.
import { type Theme, alpha, type Components } from '@mui/material/styles'
import { gray, green, orange, red, steel } from '../themePrimitives'

type Scale = Record<50 | 100 | 200 | 300 | 400 | 500 | 800 | 900, string>

/** Kolory alertu w jednym motywie: tło, ramka, ikona. */
type Tone = { background: string; border: string; icon: string }

/** Paleta alertu wg `severity`: success zielony, warning amber, error czerwony, info niebieski (steel). */
function tone(scale: Scale): { light: Tone; dark: Tone } {
  return {
    light: {
      background: scale[100],
      border: alpha(scale[300], 0.5),
      icon: scale[500],
    },
    dark: {
      background: alpha(scale[900], 0.5),
      border: alpha(scale[800], 0.5),
      icon: scale[400],
    },
  }
}

const ALERT_TONES = {
  success: {
    ...tone(green),
    // Ciemny motyw: wyraźnie zielone tło i obrys (green[900] przy alpha 0.5 było prawie czarne).
    dark: {
      ...tone(green).dark,
      background: alpha(green[700], 0.5),
      border: alpha(green[500], 0.8),
    },
  },
  info: tone(steel),
  warning: {
    ...tone(orange),
    // Zachowuje dotychczasowy wygląd amber (ikona bez zmiany w ciemnym motywie).
    dark: { ...tone(orange).dark, icon: orange[500] },
  },
  error: tone(red),
}

export const feedbackCustomizations: Components<Theme> = {
  MuiAlert: {
    styleOverrides: {
      root: ({ theme, ownerState }) => {
        const tone = ALERT_TONES[ownerState.severity ?? 'success']
        return {
          borderRadius: 10,
          backgroundColor: tone.light.background,
          color: (theme.vars || theme).palette.text.primary,
          border: `1px solid ${tone.light.border}`,
          '& .MuiAlert-icon': {
            color: tone.light.icon,
          },
          ...theme.applyStyles('dark', {
            // Tło nieprzezroczyste (toast nie może prześwitywać): papier + półprzezroczysty odcień severity.
            backgroundColor: (theme.vars || theme).palette.background.paper,
            backgroundImage: `linear-gradient(${tone.dark.background}, ${tone.dark.background})`,
            border: `1px solid ${tone.dark.border}`,
            '& .MuiAlert-icon': {
              color: tone.dark.icon,
            },
          }),
        }
      },
    },
  },
  MuiDialog: {
    styleOverrides: {
      root: ({ theme }) => ({
        '& .MuiDialog-paper': {
          borderRadius: '10px',
          border: '1px solid',
          borderColor: (theme.vars || theme).palette.divider,
        },
        // U12 (SC-V13-12, T4): krótkie dialogi poniżej `sm` — margines 16 px zamiast 32
        // (MUI liczy `maxWidth`/`width` `fullWidth` od marginesów 32 px, więc je wyrównujemy),
        // wysokość do treści z sufitem `calc(100% - 32px)`; przy niskim oknie przewija się
        // papier (`overflowY: auto` MUI), akcje zostają na dole treści. Pełny ekran długich
        // formularzy (`fullScreen`, helper `useFullScreenDialog`) zostaje bez zmian.
        [theme.breakpoints.down('sm')]: {
          '& .MuiDialog-paper:not(.MuiDialog-paperFullScreen)': {
            margin: 16,
            maxHeight: 'calc(100% - 32px)',
            maxWidth: 'calc(100% - 32px)',
          },
          '& .MuiDialog-paperFullWidth:not(.MuiDialog-paperFullScreen)': {
            width: 'calc(100% - 32px)',
          },
        },
      }),
    },
  },
  MuiLinearProgress: {
    // DEC-305: postęp w kolorze akcentu (secondary); jawne `color` w widokach (np. success)
    // wygrywa z defaultProps.
    defaultProps: {
      color: 'secondary',
    },
    styleOverrides: {
      root: ({ theme }) => ({
        height: 8,
        borderRadius: 8,
        backgroundColor: gray[200],
        ...theme.applyStyles('dark', {
          backgroundColor: gray[800],
        }),
      }),
    },
  },
}
