import { cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { initI18n } from '../i18n'

import { useDataGridLocaleText } from './useDataGridLocaleText'

afterEach(cleanup)

describe('useDataGridLocaleText', () => {
  it('dla języka pl zwraca polskie etykiety siatki', async () => {
    await initI18n('pl')

    const { result } = renderHook(() => useDataGridLocaleText())

    // `footerRowSelected` to klucz obiektu `localeText`. Etykieta wierszy na stronę w `plPL`
    // nosi nazwę `paginationRowsPerPage` — `DataGrid` przekazuje ją dalej jako
    // `MuiTablePagination.labelRowsPerPage` (material/index.js).
    expect(result.current?.footerRowSelected?.(2)).toBe('Liczba wybranych wierszy: 2')
    expect(result.current?.paginationRowsPerPage).toBe('Wierszy na stronę:')
  })

  it('dla języka en zwraca undefined (domyślne etykiety MUI)', async () => {
    await initI18n('en')

    const { result } = renderHook(() => useDataGridLocaleText())

    expect(result.current).toBeUndefined()
  })
})
