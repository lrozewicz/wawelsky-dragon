// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/shared-theme/customizations/surfaces.ts (MIT). Zmiany: importy typów (type Theme, type Components), usunięty nieaktywny komentarz eslint-disable, formatowanie Prettier.
import { alpha, type Theme, type Components } from '@mui/material/styles'
import { gray } from '../themePrimitives'

export const surfacesCustomizations: Components<Theme> = {
  MuiAccordion: {
    defaultProps: {
      elevation: 0,
      disableGutters: true,
    },
    styleOverrides: {
      root: ({ theme }) => ({
        padding: 4,
        overflow: 'clip',
        backgroundColor: (theme.vars || theme).palette.background.default,
        border: '1px solid',
        borderColor: (theme.vars || theme).palette.divider,
        ':before': {
          backgroundColor: 'transparent',
        },
        // Zmiana względem szablonu MUI (E67-z2): szablon zdejmował dolną ramkę każdemu akordeonowi, który
        // nie jest ostatnim `div` rodzica (`:not(:last-of-type)`) — samotny akordeon przed innym
        // elementem (np. stopką formularza) tracił dolną ramkę i zaokrąglenie. Teraz ramkę dzielą
        // tylko sąsiadujące akordeony w stosie (brak podwójnej linii między nimi).
        borderRadius: (theme.vars || theme).shape.borderRadius,
        '&:has(+ .MuiAccordion-root)': {
          borderBottom: 'none',
          borderBottomLeftRadius: 0,
          borderBottomRightRadius: 0,
        },
        '.MuiAccordion-root + &': {
          borderTopLeftRadius: 0,
          borderTopRightRadius: 0,
        },
      }),
    },
  },
  MuiAccordionSummary: {
    styleOverrides: {
      root: ({ theme }) => ({
        border: 'none',
        borderRadius: 8,
        '&:hover': { backgroundColor: gray[50] },
        '&:focus-visible': { backgroundColor: 'transparent' },
        ...theme.applyStyles('dark', {
          '&:hover': { backgroundColor: gray[800] },
        }),
      }),
    },
  },
  MuiAccordionDetails: {
    styleOverrides: {
      root: { mb: 20, border: 'none' },
    },
  },
  MuiPaper: {
    defaultProps: {
      elevation: 0,
    },
  },
  MuiCard: {
    styleOverrides: {
      root: ({ theme }) => {
        return {
          padding: 16,
          gap: 16,
          transition: 'all 100ms ease',
          backgroundColor: gray[50],
          borderRadius: (theme.vars || theme).shape.borderRadius,
          border: `1px solid ${(theme.vars || theme).palette.divider}`,
          boxShadow: 'none',
          ...theme.applyStyles('dark', {
            backgroundColor: gray[800],
          }),
          variants: [
            {
              props: {
                variant: 'outlined',
              },
              style: {
                border: `1px solid ${(theme.vars || theme).palette.divider}`,
                boxShadow: 'none',
                background: 'hsl(0, 0%, 100%)',
                ...theme.applyStyles('dark', {
                  background: alpha(gray[900], 0.4),
                }),
              },
            },
          ],
        }
      },
    },
  },
  MuiCardContent: {
    styleOverrides: {
      root: {
        padding: 0,
        '&:last-child': { paddingBottom: 0 },
      },
    },
  },
  MuiCardHeader: {
    styleOverrides: {
      root: {
        padding: 0,
      },
    },
  },
  MuiCardActions: {
    styleOverrides: {
      root: {
        padding: 0,
      },
    },
  },
}
