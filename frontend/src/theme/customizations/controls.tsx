// DEC-305: akcent fokusu i włączonych kontrolek = `secondary` (chłodny niebiesko-stalowy);
// przyciski główne i marka zostają `primary` (czerwień). Switch/Radio/Slider nie mają własnych
// styleOverrides (domyślne MUI malują je `primary.main`), więc domyślny kolor przełączam na
// `secondary` — jawne `color` w widokach wygrywa z defaultProps. LinearProgress jest w
// `feedback.tsx` (ten sam klucz motywu — spread w AppTheme nadpisuje defaultProps).
// Kontrast par: `theme/contrast.test.ts`.
import { type Components, type Theme } from '@mui/material/styles'

export const controlsCustomizations: Components<Theme> = {
  MuiSwitch: {
    defaultProps: {
      color: 'secondary',
    },
  },
  MuiRadio: {
    defaultProps: {
      color: 'secondary',
    },
  },
  MuiSlider: {
    defaultProps: {
      color: 'secondary',
    },
  },
  MuiCircularProgress: {
    defaultProps: {
      color: 'secondary',
    },
  },
}
