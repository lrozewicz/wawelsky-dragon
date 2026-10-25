// Źródło: material-ui v9.4.0 docs/data/material/getting-started/templates/crud-dashboard/theme/customizations/dataGrid.ts (MIT). Zmiany: importy typów (type Theme, type DataGridComponents); augmentacja @mui/x-data-grid zamiast @mui/x-data-grid-pro; import gray z ../themePrimitives; usunięta zdublowana unia typu i nieaktywny eslint-disable import/prefer-default-export; formatowanie Prettier.
import { paperClasses } from '@mui/material/Paper'
import { alpha, type Theme } from '@mui/material/styles'
import type { DataGridComponents } from '@mui/x-data-grid/themeAugmentation'
import { menuItemClasses } from '@mui/material/MenuItem'
import { listItemIconClasses } from '@mui/material/ListItemIcon'
import { iconButtonClasses } from '@mui/material/IconButton'
import { inputBaseClasses } from '@mui/material/InputBase'
import { checkboxClasses } from '@mui/material/Checkbox'
import { listClasses } from '@mui/material/List'
import { gridClasses } from '@mui/x-data-grid'
import { tablePaginationClasses } from '@mui/material/TablePagination'
import { gray, steel } from '../themePrimitives'

export const dataGridCustomizations: DataGridComponents<Theme> = {
  MuiDataGrid: {
    styleOverrides: {
      root: ({ theme }) => ({
        '--DataGrid-overlayHeight': '300px',
        overflow: 'clip',
        borderColor: (theme.vars || theme).palette.divider,
        backgroundColor: (theme.vars || theme).palette.background.default,
        [`& .${gridClasses.columnHeader}`]: {
          backgroundColor: (theme.vars || theme).palette.background.paper,
        },
        // E67-z2 T4: ramka focusu komórki tylko dla klawiatury — klik myszą w przycisk w komórce
        // (np. ⋮ w „Akcje”) zostawiał czerwoną ramkę `:focus-within` wokół całej komórki.
        [`& .${gridClasses.cell}:focus, & .${gridClasses.cell}:focus-within`]: {
          outline: 'none',
        },
        [`& .${gridClasses.cell}:focus-visible, & .${gridClasses.cell}:has(:focus-visible)`]: {
          outline: `2px solid ${alpha(steel[500], 0.5)}`,
          outlineOffset: -2,
        },
        [`& .${gridClasses.footerContainer}`]: {
          backgroundColor: (theme.vars || theme).palette.background.paper,
        },
        [`& .${checkboxClasses.root}`]: {
          padding: theme.spacing(0.5),
          '& > svg': {
            fontSize: '1rem',
          },
        },
        [`& .${tablePaginationClasses.root}`]: {
          marginRight: theme.spacing(1),
          '& .MuiIconButton-root': {
            maxHeight: 32,
            maxWidth: 32,
            '& > svg': {
              fontSize: '1rem',
            },
          },
        },
      }),
      cell: ({ theme }) => ({ borderTopColor: (theme.vars || theme).palette.divider }),
      menu: ({ theme }) => ({
        borderRadius: theme.shape.borderRadius,
        backgroundImage: 'none',
        [`& .${paperClasses.root}`]: {
          border: `1px solid ${(theme.vars || theme).palette.divider}`,
        },

        [`& .${menuItemClasses.root}`]: {
          margin: '0 4px',
        },
        [`& .${listItemIconClasses.root}`]: {
          marginRight: 0,
        },
        [`& .${listClasses.root}`]: {
          paddingLeft: 0,
          paddingRight: 0,
        },
      }),

      row: ({ theme }) => ({
        '&:last-of-type': { borderBottom: `1px solid ${(theme.vars || theme).palette.divider}` },
        '&:hover': {
          backgroundColor: (theme.vars || theme).palette.action.hover,
        },
        '&.Mui-selected': {
          // DEC-305: zaznaczony wiersz w kolorze akcentu (secondary); `alpha()` MUI nie przyjmuje
          // `var()` — light steel[500], dark steel[300] niżej. Hover na zaznaczonym lekko
          // mocniejszy — nie czyści zaznaczenia do neutralnego szarego.
          background: alpha(steel[500], 0.14),
          '&:hover': {
            backgroundColor: alpha(steel[500], 0.2),
          },
          ...theme.applyStyles('dark', {
            background: alpha(steel[300], 0.18),
            '&:hover': {
              backgroundColor: alpha(steel[300], 0.24),
            },
          }),
        },
      }),
      iconButtonContainer: ({ theme }) => ({
        [`& .${iconButtonClasses.root}`]: {
          border: 'none',
          backgroundColor: 'transparent',
          '&:hover': {
            backgroundColor: alpha(theme.palette.action.selected, 0.3),
          },
          '&:active': {
            backgroundColor: gray[200],
          },
          ...theme.applyStyles('dark', {
            color: gray[50],
            '&:hover': {
              backgroundColor: gray[800],
            },
            '&:active': {
              backgroundColor: gray[900],
            },
          }),
        },
      }),
      menuIconButton: ({ theme }) => ({
        border: 'none',
        backgroundColor: 'transparent',
        '&:hover': {
          backgroundColor: gray[100],
        },
        '&:active': {
          backgroundColor: gray[200],
        },
        ...theme.applyStyles('dark', {
          color: gray[50],
          '&:hover': {
            backgroundColor: gray[800],
          },
          '&:active': {
            backgroundColor: gray[900],
          },
        }),
      }),
      filterForm: ({ theme }) => ({
        gap: theme.spacing(1),
        alignItems: 'flex-end',
      }),
      columnsManagementHeader: ({ theme }) => ({
        paddingRight: theme.spacing(3),
        paddingLeft: theme.spacing(3),
      }),
      columnHeaderTitleContainer: {
        flexGrow: 1,
        justifyContent: 'space-between',
      },
      columnHeaderDraggableContainer: { paddingRight: 2 },
      toolbar: ({ theme }) => ({
        backgroundColor: (theme.vars || theme).palette.background.paper,
      }),
      toolbarQuickFilter: {
        [`& .${inputBaseClasses.root}`]: {
          marginLeft: 6,
          marginRight: 6,
        },
        [`& .${iconButtonClasses.root}`]: {
          height: '36px',
          width: '36px',
        },
        [`& .${iconButtonClasses.edgeEnd}`]: {
          border: 'none',
          height: '28px',
          width: '28px',
        },
      },
    },
  },
}
