/**
 * Wspólna lokalizacja siatek `DataGrid` (kontrakt WP E3-H4 §T1): dla języka polskiego zwraca
 * `localeText` z pakietu `plPL` (`@mui/x-data-grid/locales`), a dla pozostałych języków `undefined`,
 * czyli domyślne etykiety MUI. Logika przeniesiona z `FilesGrid.tsx` (dotąd powtarzana w trzech
 * siatkach). Typ `Partial<GridLocaleText>` to dokładnie typ, którego oczekuje prop `localeText`
 * `DataGrid` i typ wartości w `plPL`.
 */
import { plPL } from '@mui/x-data-grid/locales'
import type { GridLocaleText } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'

import { resolveLanguage } from '../i18n'

export function useDataGridLocaleText(): Partial<GridLocaleText> | undefined {
  const { i18n } = useTranslation()

  return resolveLanguage(i18n.language) === 'pl'
    ? plPL.components.MuiDataGrid.defaultProps.localeText
    : undefined
}
