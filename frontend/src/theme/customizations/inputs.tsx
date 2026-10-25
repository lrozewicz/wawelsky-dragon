// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/shared-theme/customizations/inputs.tsx (MIT). Zmiany: importy typów (type Theme, type Components), usunięty nieaktywny komentarz eslint-disable, formatowanie Prettier.
import { alpha, type Theme, type Components } from '@mui/material/styles'
import { outlinedInputClasses } from '@mui/material/OutlinedInput'
import { inputLabelClasses } from '@mui/material/InputLabel'
import { svgIconClasses } from '@mui/material/SvgIcon'
import { toggleButtonGroupClasses } from '@mui/material/ToggleButtonGroup'
import { toggleButtonClasses } from '@mui/material/ToggleButton'
import CheckBoxOutlineBlankRoundedIcon from '@mui/icons-material/CheckBoxOutlineBlankRounded'
import CheckRoundedIcon from '@mui/icons-material/CheckRounded'
import RemoveRoundedIcon from '@mui/icons-material/RemoveRounded'
import { gray, steel } from '../themePrimitives'

/**
 * Kolory przycisku `contained` (primary) w stanie `disabled`. MUI zeruje wtedy tylko
 * `backgroundColor` i `boxShadow`, więc gradient i obramowanie z motywu zostawały — a tekst
 * z `action.disabled` (30% bieli w dark) był nieczytelny na jasnej pigułce (D-maj2 QA E3-H4).
 * Para tekst/tło jest mierzona w `theme/contrast.test.ts`.
 */
export const containedDisabledColors = {
  light: { color: gray[500], backgroundColor: gray[200] },
  dark: { color: gray[400], backgroundColor: gray[700] },
} as const

/**
 * Kolor etykiety pola `outlined` w fokusie (DEC-305: akcent fokusu = `secondary`). W dark
 * `steel[300]` daje 9.4:1 na papierze, w light `steel[600]` 6.8:1 — obie pary ≥ AA 4.5:1
 * (`brand[400]` — stary kolor fokusu — miał w ciemnym motywie tylko 3.5:1; MAJOR M1,
 * QA E5-H8d-1). Pary mierzone w `theme/contrast.test.ts` (tła paper i default).
 */
export const focusedLabelColor = {
  light: steel[600],
  dark: steel[300],
} as const

export const inputsCustomizations: Components<Theme> = {
  MuiButtonBase: {
    defaultProps: {
      disableTouchRipple: true,
      disableRipple: true,
    },
    styleOverrides: {
      root: ({ theme }) => ({
        boxSizing: 'border-box',
        transition: 'all 100ms ease-in',
        '&:focus-visible': {
          // DEC-305: fokus w kolorze akcentu (secondary), nie czerwieni marki. `alpha()` MUI
          // nie przyjmuje `var()` — odcienie steel wprost, dark nadpisany niżej.
          outline: `3px solid ${alpha(steel[500], 0.5)}`,
          outlineOffset: '2px',
        },
        ...theme.applyStyles('dark', {
          '&:focus-visible': {
            outline: `3px solid ${alpha(steel[300], 0.5)}`,
          },
        }),
      }),
    },
  },
  MuiButton: {
    styleOverrides: {
      root: ({ theme }) => ({
        boxShadow: 'none',
        borderRadius: (theme.vars || theme).shape.borderRadius,
        textTransform: 'none',
        variants: [
          {
            props: {
              size: 'small',
            },
            style: {
              height: '2.25rem',
              padding: '8px 12px',
            },
          },
          {
            props: {
              size: 'medium',
            },
            style: {
              height: '2.5rem', // 40px
            },
          },
          {
            props: {
              color: 'primary',
              variant: 'contained',
            },
            style: {
              color: 'white',
              backgroundColor: gray[900],
              backgroundImage: `linear-gradient(to bottom, ${gray[700]}, ${gray[800]})`,
              boxShadow: `inset 0 1px 0 ${gray[600]}, inset 0 -1px 0 1px hsl(220, 0%, 0%)`,
              border: `1px solid ${gray[700]}`,
              '&:hover': {
                backgroundImage: 'none',
                backgroundColor: gray[700],
                boxShadow: 'none',
              },
              '&:active': {
                backgroundColor: gray[800],
              },
              // `contained` disabled: bez gradientu i obramowania z motywu, kontrast pary
              // tekst/tło ≥ 3:1 (D-maj2 QA E3-H4).
              '&.Mui-disabled': {
                color: containedDisabledColors.light.color,
                backgroundColor: containedDisabledColors.light.backgroundColor,
                backgroundImage: 'none',
                border: `1px solid ${containedDisabledColors.light.backgroundColor}`,
                boxShadow: 'none',
              },
              ...theme.applyStyles('dark', {
                color: 'black',
                backgroundColor: gray[50],
                backgroundImage: `linear-gradient(to bottom, ${gray[100]}, ${gray[50]})`,
                boxShadow: 'inset 0 -1px 0  hsl(220, 30%, 80%)',
                border: `1px solid ${gray[50]}`,
                '&:hover': {
                  backgroundImage: 'none',
                  backgroundColor: gray[300],
                  boxShadow: 'none',
                },
                '&:active': {
                  backgroundColor: gray[400],
                },
                '&.Mui-disabled': {
                  color: containedDisabledColors.dark.color,
                  backgroundColor: containedDisabledColors.dark.backgroundColor,
                  backgroundImage: 'none',
                  border: `1px solid ${containedDisabledColors.dark.backgroundColor}`,
                  boxShadow: 'none',
                },
              }),
            },
          },
          {
            props: {
              color: 'secondary',
              variant: 'contained',
            },
            style: {
              // DEC-305: przycisk `secondary` idzie za paletą akcentu (niebiesko-stalowy),
              // żeby nie zlewał się z przyciskami głównymi (primary = czerwień marki).
              color: 'white',
              backgroundColor: steel[500],
              backgroundImage: `linear-gradient(to bottom, ${steel[600]}, ${steel[700]})`,
              boxShadow: `inset 0 2px 0 ${alpha(steel[400], 0.2)}, inset 0 -2px 0 ${alpha(steel[800], 0.4)}`,
              border: `1px solid ${steel[700]}`,
              '&:hover': {
                backgroundColor: steel[600],
                boxShadow: 'none',
              },
              '&:active': {
                backgroundColor: steel[700],
                backgroundImage: 'none',
              },
            },
          },
          {
            props: {
              variant: 'outlined',
            },
            style: {
              color: (theme.vars || theme).palette.text.primary,
              border: '1px solid',
              borderColor: gray[200],
              backgroundColor: alpha(gray[50], 0.3),
              '&:hover': {
                backgroundColor: gray[100],
                borderColor: gray[300],
              },
              '&:active': {
                backgroundColor: gray[200],
              },
              ...theme.applyStyles('dark', {
                backgroundColor: gray[800],
                borderColor: gray[700],

                '&:hover': {
                  backgroundColor: gray[900],
                  borderColor: gray[600],
                },
                '&:active': {
                  backgroundColor: gray[900],
                },
              }),
            },
          },
          {
            props: {
              color: 'secondary',
              variant: 'outlined',
            },
            style: {
              // DEC-305: akcent secondary w obu motywach (kontrast tekstu ≥ 8:1 na tle).
              color: steel[700],
              border: '1px solid',
              borderColor: steel[200],
              backgroundColor: steel[50],
              '&:hover': {
                backgroundColor: steel[100],
                borderColor: steel[400],
              },
              '&:active': {
                backgroundColor: alpha(steel[200], 0.7),
              },
              ...theme.applyStyles('dark', {
                color: steel[200],
                border: '1px solid',
                borderColor: steel[800],
                backgroundColor: alpha(steel[900], 0.3),
                '&:hover': {
                  borderColor: steel[700],
                  backgroundColor: alpha(steel[900], 0.6),
                },
                '&:active': {
                  backgroundColor: alpha(steel[900], 0.5),
                },
              }),
            },
          },
          {
            props: {
              variant: 'text',
            },
            style: {
              color: gray[600],
              '&:hover': {
                backgroundColor: gray[100],
              },
              '&:active': {
                backgroundColor: gray[200],
              },
              ...theme.applyStyles('dark', {
                color: gray[50],
                '&:hover': {
                  backgroundColor: gray[700],
                },
                '&:active': {
                  backgroundColor: alpha(gray[700], 0.7),
                },
              }),
            },
          },
          {
            props: {
              color: 'secondary',
              variant: 'text',
            },
            style: {
              // DEC-305: akcent secondary w obu motywach.
              color: steel[700],
              '&:hover': {
                backgroundColor: alpha(steel[100], 0.5),
              },
              '&:active': {
                backgroundColor: alpha(steel[200], 0.7),
              },
              ...theme.applyStyles('dark', {
                color: steel[100],
                '&:hover': {
                  backgroundColor: alpha(steel[900], 0.5),
                },
                '&:active': {
                  backgroundColor: alpha(steel[900], 0.3),
                },
              }),
            },
          },
        ],
      }),
    },
  },
  MuiIconButton: {
    styleOverrides: {
      root: ({ theme }) => ({
        boxShadow: 'none',
        borderRadius: (theme.vars || theme).shape.borderRadius,
        textTransform: 'none',
        fontWeight: theme.typography.fontWeightMedium,
        letterSpacing: 0,
        color: (theme.vars || theme).palette.text.primary,
        border: '1px solid ',
        borderColor: gray[200],
        backgroundColor: alpha(gray[50], 0.3),
        '&:hover': {
          backgroundColor: gray[100],
          borderColor: gray[300],
        },
        '&:active': {
          backgroundColor: gray[200],
        },
        ...theme.applyStyles('dark', {
          backgroundColor: gray[800],
          borderColor: gray[700],
          '&:hover': {
            backgroundColor: gray[900],
            borderColor: gray[600],
          },
          '&:active': {
            backgroundColor: gray[900],
          },
        }),
        variants: [
          {
            props: {
              size: 'small',
            },
            style: {
              width: '2.25rem',
              height: '2.25rem',
              padding: '0.25rem',
              [`& .${svgIconClasses.root}`]: { fontSize: '1rem' },
            },
          },
          {
            props: {
              size: 'medium',
            },
            style: {
              width: '2.5rem',
              height: '2.5rem',
            },
          },
        ],
      }),
    },
  },
  MuiToggleButtonGroup: {
    styleOverrides: {
      root: ({ theme }) => ({
        borderRadius: '10px',
        boxShadow: `0 4px 16px ${alpha(gray[400], 0.2)}`,
        [`& .${toggleButtonGroupClasses.selected}`]: {
          // DEC-305: zaznaczony segment w kolorze akcentu (w light MUI i tak wygrywa z tym
          // tekstem `text.primary` — patrz komentarz w contrast.test.ts).
          color: steel[600],
        },
        ...theme.applyStyles('dark', {
          [`& .${toggleButtonGroupClasses.selected}`]: {
            color: steel[300],
          },
          boxShadow: `0 4px 16px ${alpha(steel[700], 0.5)}`,
        }),
      }),
    },
  },
  MuiToggleButton: {
    styleOverrides: {
      root: ({ theme }) => ({
        padding: '12px 16px',
        textTransform: 'none',
        borderRadius: '10px',
        fontWeight: 500,
        ...theme.applyStyles('dark', {
          color: gray[400],
          boxShadow: '0 4px 16px rgba(0, 0, 0, 0.5)',
          [`&.${toggleButtonClasses.selected}`]: {
            // D5 QA E3-7 / DEC-305: jasny odcień akcentu (secondary) — na półprzezroczystym tle
            // aktywnego segmentu (alpha(text.primary, 0.16)) daje ~6.8:1 (AA z zapasem).
            color: steel[300],
          },
        }),
      }),
    },
  },
  MuiCheckbox: {
    defaultProps: {
      disableRipple: true,
      icon: <CheckBoxOutlineBlankRoundedIcon sx={{ color: 'hsla(210, 0%, 0%, 0.0)' }} />,
      checkedIcon: <CheckRoundedIcon sx={{ height: 14, width: 14 }} />,
      indeterminateIcon: <RemoveRoundedIcon sx={{ height: 14, width: 14 }} />,
    },
    styleOverrides: {
      root: ({ theme }) => ({
        margin: 10,
        height: 16,
        width: 16,
        borderRadius: 5,
        border: '1px solid ',
        borderColor: alpha(gray[300], 0.8),
        boxShadow: '0 0 0 1.5px hsla(210, 0%, 0%, 0.04) inset',
        backgroundColor: alpha(gray[100], 0.4),
        transition: 'border-color, background-color, 120ms ease-in',
        '&:hover': {
          borderColor: steel[300],
        },
        '&.Mui-focusVisible': {
          // DEC-305: fokus i stan włączony w kolorze akcentu (secondary), nie czerwieni.
          outline: `3px solid ${alpha(steel[500], 0.5)}`,
          outlineOffset: '2px',
          borderColor: steel[400],
        },
        '&.Mui-checked': {
          color: 'white',
          backgroundColor: steel[500],
          borderColor: steel[500],
          boxShadow: `none`,
          '&:hover': {
            backgroundColor: steel[600],
          },
        },
        ...theme.applyStyles('dark', {
          borderColor: alpha(gray[700], 0.8),
          boxShadow: '0 0 0 1.5px hsl(210, 0%, 0%) inset',
          backgroundColor: alpha(gray[900], 0.8),
          '&:hover': {
            borderColor: steel[300],
          },
          '&.Mui-focusVisible': {
            borderColor: steel[400],
            outline: `3px solid ${alpha(steel[500], 0.5)}`,
            outlineOffset: '2px',
          },
          // Steel[500] także w dark (jasny steel[300] zabiłby biały „haczyk” — 2:1); kontrast
          // ikony na tle 5.5:1, hover rozjaśnia do steel[400] (3.4:1 — grafika ≥ 3:1).
          '&.Mui-checked': {
            color: 'white',
            backgroundColor: steel[500],
            borderColor: steel[500],
            '&:hover': {
              backgroundColor: steel[400],
            },
          },
        }),
      }),
    },
  },
  MuiInputBase: {
    styleOverrides: {
      root: {
        border: 'none',
      },
      input: {
        '&::placeholder': {
          opacity: 0.7,
          color: gray[500],
        },
      },
    },
  },
  MuiOutlinedInput: {
    styleOverrides: {
      input: {
        padding: 0,
      },
      root: ({ theme }) => ({
        padding: '8px 12px',
        color: (theme.vars || theme).palette.text.primary,
        borderRadius: (theme.vars || theme).shape.borderRadius,
        border: `1px solid ${(theme.vars || theme).palette.divider}`,
        backgroundColor: (theme.vars || theme).palette.background.default,
        transition: 'border 120ms ease-in',
        '&:hover': {
          borderColor: gray[400],
        },
        // D1 (QA E5-H9-1): korzeń maluje `border` z `divider` (notchedOutline wyłączony), więc
        // standardowa reguła MUI dla notchedOutline nic tu nie robi i ramka błędu zostawała
        // szara. Błąd bije hover i fokus (jak w `MuiFormLabel` wyżej).
        '&.Mui-error': {
          borderColor: (theme.vars || theme).palette.error.main,
        },
        '&.Mui-error:hover': {
          borderColor: (theme.vars || theme).palette.error.main,
        },
        '&.Mui-error.Mui-focused': {
          borderColor: (theme.vars || theme).palette.error.main,
        },
        [`&.${outlinedInputClasses.focused}`]: {
          // DEC-305: fokus pola (ramka + obrys) w kolorze akcentu — nie czerwieni marki.
          // `alpha()` MUI nie przyjmuje `var()` — odcienie steel wprost (light steel[500],
          // dark steel[300] niżej); kontrasty: `theme/contrast.test.ts`.
          outline: `3px solid ${alpha(steel[500], 0.5)}`,
          borderColor: steel[500],
        },
        ...theme.applyStyles('dark', {
          '&:hover': {
            borderColor: gray[500],
          },
          '&.Mui-error': {
            borderColor: (theme.vars || theme).palette.error.main,
          },
          '&.Mui-error:hover': {
            borderColor: (theme.vars || theme).palette.error.main,
          },
          '&.Mui-error.Mui-focused': {
            borderColor: (theme.vars || theme).palette.error.main,
          },
          [`&.${outlinedInputClasses.focused}`]: {
            outline: `3px solid ${alpha(steel[300], 0.5)}`,
            borderColor: steel[300],
          },
        }),
        variants: [
          // Stała wysokość tylko dla pól jednoliniowych. `InputBase` centruje zawartość
          // (`display: inline-flex; align-items: center`), więc wymuszona wysokość na polu
          // `multiline` wypychała tekstarea poza obramowanie, a zwinięta etykieta
          // (`translate(14px, -9px)`) wchodziła na pierwszy wiersz tekstu (D-maj1 QA E3-H4).
          {
            props: {
              size: 'small',
              multiline: false,
            },
            style: {
              height: '2.25rem',
            },
          },
          {
            props: {
              size: 'medium',
              multiline: false,
            },
            style: {
              height: '2.5rem',
            },
          },
        ],
      }),
      notchedOutline: {
        border: 'none',
      },
    },
  },
  MuiInputAdornment: {
    styleOverrides: {
      root: ({ theme }) => ({
        color: (theme.vars || theme).palette.grey[500],
        ...theme.applyStyles('dark', {
          color: (theme.vars || theme).palette.grey[400],
        }),
      }),
    },
  },
  MuiFormLabel: {
    styleOverrides: {
      root: ({ theme }) => ({
        typography: theme.typography.caption,
        marginBottom: 8,
        '&.Mui-focused': {
          color: focusedLabelColor.light,
        },
        // T4 (MINOR review T1): błąd bije fokus — w polu z błędem w fokusie etykieta zostaje
        // w kolorze BŁĘDU (`error.main`), nie w brandowym kolorze fokusu. Reguła powtórzona
        // w bloku dark: selektor `applyStyles('dark')` podnosi specyficzność `&.Mui-focused`.
        '&.Mui-error.Mui-focused': {
          color: (theme.vars || theme).palette.error.main,
        },
        ...theme.applyStyles('dark', {
          '&.Mui-focused': {
            color: focusedLabelColor.dark,
          },
          '&.Mui-error.Mui-focused': {
            color: (theme.vars || theme).palette.error.main,
          },
        }),
      }),
    },
  },
  MuiInputLabel: {
    styleOverrides: {
      root: ({ theme, ownerState }) => ({
        // Etykieta uniesiona (shrink) leży NA krawędzi pola outlined: dolna część tekstu wchodzi
        // na obrys fokusu i wypełnienie pola (`background.default`), górna na tło dialogu — bez
        // własnego tła tekst „tonie” i wygląda na ucięty (MAJOR M1, QA E5-H8d-1). Łatka w kolorze
        // powierzchni (paper) imituje klasyczny notch MUI; poszerzenie i ujemny margines trzymają
        // tekst na pierwotnej siatce 14 px od krawędzi pola.
        ...(ownerState?.variant === 'outlined' && {
          [`&.${inputLabelClasses.shrink}`]: {
            backgroundColor: (theme.vars || theme).palette.background.paper,
            padding: '0 5px',
            marginLeft: -5,
          },
        }),
      }),
    },
  },
}
