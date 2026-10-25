/**
 * Filtr metadanych listy dokumentów (WP E6-1b T5b): otwarcie popovera z pustym stanem tworzy
 * „Warunek 1”, chip „Metadane: n warunków” z × woła `onClear`, „Zastosuj” woła `onApply` i
 * zamyka popover, „Wyczyść” woła `onClear` i zostawia popover otwarty ze świeżym wierszem.
 * Stan roboczy żyje w rodzicu (harness) — zmiana warunku wraca jako props (komponent kontrolowany).
 */
import { useState } from 'react'
import type { JSX } from 'react'
import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useSummary, type SummaryFixture } from '../../../test/metadataBuilder'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { MetadataFilterBar } from './MetadataFilterBar'
import type { MetaCondition } from '../../metadata/types'

afterEach(cleanup)

/** Summary z kluczami — kreator pokazuje wiersze tylko gdy bazy mają metadany (`hasAny`). */
const SUMMARY: SummaryFixture = {
  typ: { type: 'string', values: [['raport', 2]] },
  rok: { type: 'string', values: [['2023', 1]] },
}

/** Rodzic z prawdziwym stanem roboczym (jak `DatasetFilesTab`): warunki + aktywna liczba. */
function Harness(props: {
  onApply: () => void
  onClear: () => void
  activeCount?: number
  initialConditions?: MetaCondition[]
}): JSX.Element {
  const [logic, setLogic] = useState<'and' | 'or'>('and')
  const [conditions, setConditions] = useState<MetaCondition[]>(props.initialConditions ?? [])

  return (
    <MetadataFilterBar
      datasetId="ds-1"
      logic={logic}
      conditions={conditions}
      activeCount={props.activeCount ?? 0}
      onChange={(nextLogic, nextConditions) => {
        setLogic(nextLogic)
        setConditions(nextConditions)
      }}
      onApply={props.onApply}
      onClear={props.onClear}
    />
  )
}

/** Otwiera popover i czeka na montowanie treści (MUI Modal montuje w efekcie). */
async function openBuilder(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByTestId('metadata-filter'))
  await screen.findByRole('group', { name: 'Warunek 1' })
}

describe('MetadataFilterBar', () => {
  it('dataset bez metadanych: komunikat z linkiem do Konfiguracji (kontrakt §4)', async () => {
    const user = userEvent.setup()
    // Summary puste → hasAny false → kreator pokazuje komunikat zamiast wierszy.
    useSummary({})
    await renderWithProviders(<Harness onApply={vi.fn()} onClear={vi.fn()} />, {
      routes: ['/dataset/configuration/$id'],
    })

    await user.click(screen.getByTestId('metadata-filter'))
    await screen.findByText(/Bazy nie mają metadanych/)

    const link = screen.getByRole('link', { name: 'Konfiguracji datasetu' })
    expect(link).toHaveAttribute('href', '/dataset/configuration/ds-1')
  })

  it('otwarcie z pustym stanem tworzy pierwszy (pusty) warunek — bez przełącznika trybów', async () => {
    const user = userEvent.setup()
    useSummary(SUMMARY)
    await renderWithProviders(<Harness onApply={vi.fn()} onClear={vi.fn()} />, { routes: [] })

    await openBuilder(user)

    const row = screen.getByRole('group', { name: 'Warunek 1' })
    // Tryb ręczny narzucony widokiem — radiomy trybów nie ma (modes=['manual']).
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
    // Pusty klucz oznaczony aria-invalid (kontrakt §4: walidacja warunku bez klucza).
    expect(within(row).getByRole('combobox', { name: 'Klucz' })).toHaveAttribute('aria-invalid')
  })

  it('kreator jest kontrolowany: wybór klucza wraca przez onChange do rodzica', async () => {
    const user = userEvent.setup()
    useSummary(SUMMARY)
    await renderWithProviders(<Harness onApply={vi.fn()} onClear={vi.fn()} />, { routes: [] })

    await openBuilder(user)
    // Otwarcie z pustym stanem: świeży wiersz z pustym kluczem (kontrolowany — '' w polu).
    expect(screen.getByRole('combobox', { name: 'Klucz' })).toHaveValue('')

    await user.click(screen.getByRole('combobox', { name: 'Klucz' }))
    await user.click(await screen.findByRole('option', { name: 'typ' }))

    // Wybór przeszedł przez onChange do rodzica i wrócił jako props (komponent kontrolowany).
    expect(screen.getByRole('combobox', { name: 'Klucz' })).toHaveValue('typ')
  })

  it('„Zastosuj” woła onApply i zamyka popover', async () => {
    const user = userEvent.setup()
    const onApply = vi.fn()
    useSummary(SUMMARY)
    await renderWithProviders(
      <Harness
        onApply={onApply}
        onClear={vi.fn()}
        initialConditions={[{ key: 'typ', op: '=', value: 'raport' }]}
      />,
      { routes: [] },
    )

    await openBuilder(user)

    await user.click(screen.getByRole('button', { name: 'Zastosuj' }))

    expect(onApply).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('group', { name: 'Warunek 1' })).not.toBeInTheDocument()
  })

  it('chip aktywnego filtra ma liczbę warunków w liczbie mnogiej, × woła onClear', async () => {
    const user = userEvent.setup()
    const onClear = vi.fn()
    await renderWithProviders(<Harness onApply={vi.fn()} onClear={onClear} activeCount={2} />, {
      routes: [],
    })

    const chip = screen.getByTestId('metadata-filter-chip')
    expect(chip).toHaveTextContent('Metadane: 2 warunki')

    // × z aria-label (wzorzec MUI: svg z aria-label; e2e klika po atrybucie).
    await user.click(screen.getByLabelText('Usuń filtr metadanych'))
    expect(onClear).toHaveBeenCalledTimes(1)
  })

  it('„Wyczyść” woła onClear i zostawia popover otwarty ze świeżym pustym wierszem', async () => {
    const user = userEvent.setup()
    const onClear = vi.fn()
    useSummary(SUMMARY)
    await renderWithProviders(
      <Harness
        onApply={vi.fn()}
        onClear={onClear}
        activeCount={1}
        initialConditions={[{ key: 'typ', op: '=', value: 'raport' }]}
      />,
      { routes: [] },
    )

    await openBuilder(user)
    expect(screen.getByRole('combobox', { name: 'Klucz' })).toHaveValue('typ')

    await user.click(screen.getByRole('button', { name: 'Wyczyść' }))

    expect(onClear).toHaveBeenCalledTimes(1)
    // Popover zostaje otwarty; stan roboczy to jeden świeży, pusty wiersz — kreator gotowy
    // do układania filtra od nowa.
    expect(screen.getByRole('group', { name: 'Warunek 1' })).toBeVisible()
    expect(screen.getByRole('combobox', { name: 'Klucz' })).toHaveValue('')
  })

  it('bez aktywnego filtra chip jest ukryty', async () => {
    await renderWithProviders(<Harness onApply={vi.fn()} onClear={vi.fn()} />, { routes: [] })

    expect(screen.queryByTestId('metadata-filter-chip')).not.toBeInTheDocument()
  })

  it('chip ma bazę 0 od md i min-width 0 — rośnie w wierszu z wielokropkiem zamiast wypychać „Prześlij plik” (QA V12-z-1 C15)', async () => {
    // jsdom nie liczy układu — asercja na regułę sx w arkuszu (pełny układ pilnuje e2e S30).
    // `flex-wrap` łamie wiersz po bazowych rozmiarach, więc od md chip potrzebuje
    // `flex-basis: 0` (rośnie w wolne miejsce), nie tylko możliwości kurczenia.
    useSummary(SUMMARY)
    await renderWithProviders(<Harness onApply={vi.fn()} onClear={vi.fn()} activeCount={1} />, {
      routes: [],
    })

    const chip = screen.getByTestId('metadata-filter-chip')
    const names = [...chip.classList]
    const css: string[] = []
    for (const sheet of Array.from(document.styleSheets)) {
      for (const rule of Array.from(sheet.cssRules)) {
        const text = rule.cssText
        if (names.some((name) => text.includes(name))) css.push(text)
      }
    }
    const joined = css.join('\n')
    expect(joined).toMatch(/min-width:\s*0/)
    // Reguła md (media query) w tym samym arkuszu: `flex: 1 1 0` (jsdom zapisuje basis jako 0%).
    expect(joined).toMatch(/flex:\s*1 1 0/)
  })
})
