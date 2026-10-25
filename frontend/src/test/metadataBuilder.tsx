/**
 * Wspólne atrapy i harness testów kreatora warunków metadanych (`features/metadata`):
 * podsumowanie wartości z drutu E6-1a, rodzic z prawdziwym stanem (komponent kontrolowany)
 * i pomocnik klikania opcji w menu MUI Select. Poza plikami testowymi — importują je oba
 * pliki `MetadataConditionBuilder*.test.tsx`.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { useState } from 'react'
import type { JSX } from 'react'
import type { Mock } from 'vitest'
import { vi } from 'vitest'

import { apiUrl } from './msw/handlers'
import { server } from './msw/server'
import { renderWithProviders } from './renderWithProviders'

import type { MetadataConditionBuilderProps } from '../features/metadata/MetadataConditionBuilder'
import { MetadataConditionBuilder } from '../features/metadata/MetadataConditionBuilder'
import type { MetaFilter } from '../features/metadata/types'

/** Podsumowanie wartości (drut E6-1a): klucz → typ + pary [wartość, liczba]. */
export type SummaryFixture = Record<string, { type: string; values: Array<[string, number]> }>

export const FIXTURE_SUMMARY: SummaryFixture = {
  rok: {
    type: 'string',
    values: [
      ['2023', 1],
      ['2024', 1],
    ],
  },
  typ: {
    type: 'string',
    values: [
      ['raport', 1],
      ['ustawa', 1],
    ],
  },
}

/** Nadpisuje `GET …/metadata/summary` dla wszystkich baz; `{}` = bazy bez metadanych. */
export function useSummary(summary: SummaryFixture): void {
  server.use(
    http.get(apiUrl('/api/v1/datasets/:id/metadata/summary'), () =>
      HttpResponse.json({ code: 0, data: { summary } }),
    ),
  )
}

/**
 * Rodzic z prawdziwym stanem (komponent jest kontrolowany — emisja wraca jako props),
 * ze szpiegiem `onChange` do asercji.
 */
export async function renderBuilder(
  initial: MetaFilter,
  overrides: Partial<MetadataConditionBuilderProps> = {},
): Promise<{ onChange: Mock }> {
  const onChange = vi.fn()
  function Harness(): JSX.Element {
    const [value, setValue] = useState(initial)
    return (
      <MetadataConditionBuilder
        value={value}
        onChange={(next) => {
          onChange(next)
          setValue(next)
        }}
        datasetIds={['ds-1']}
        modes={['off', 'manual', 'auto', 'semi_auto']}
        {...overrides}
      />
    )
  }
  await renderWithProviders(<Harness />, { routes: ['/dataset/configuration/$id'] })
  return { onChange }
}

/** Kliknięcie opcji w menu MUI Select po tekście (nazwy MUI liczy inaczej). */
export async function chooseSelectOption(label: string, optionText: string): Promise<void> {
  const user = userEvent.setup()
  await user.click(screen.getByLabelText(label))
  const options = await screen.findAllByRole('option')
  const found = options.find((option) => option.textContent === optionText)
  if (found === undefined) throw new Error(`Brak opcji listy: ${optionText}`)
  await user.click(found)
}

export const MANUAL_FILTER: MetaFilter = {
  method: 'manual',
  logic: 'and',
  manual: [{ key: 'typ', op: '=', value: 'raport' }],
  semi_auto: [],
}
