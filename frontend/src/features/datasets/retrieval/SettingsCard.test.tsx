import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { FIXTURE_SUMMARY, useSummary } from '../../../test/metadataBuilder'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DEFAULT_SETTINGS } from './schema'
import type { RetrievalSettings } from './schema'
import { SettingsCard } from './SettingsCard'

afterEach(cleanup)

type Overrides = {
  settings?: RetrievalSettings
  question?: string
  running?: boolean
  rerankOptions?: string[]
  datasetId?: string
}

/** Render karty z atrapami akcji; zwraca funkcje-spy przekazane w propsach. */
async function renderCard(overrides: Overrides = {}) {
  const onSettingsChange = vi.fn()
  const onQuestionChange = vi.fn()
  const onRun = vi.fn()

  await renderWithProviders(
    <SettingsCard
      settings={overrides.settings ?? DEFAULT_SETTINGS}
      question={overrides.question ?? ''}
      running={overrides.running ?? false}
      rerankOptions={overrides.rerankOptions ?? []}
      datasetId={overrides.datasetId ?? 'ds-1'}
      onSettingsChange={onSettingsChange}
      onQuestionChange={onQuestionChange}
      onRun={onRun}
    />,
  )

  return { onSettingsChange, onQuestionChange, onRun }
}

describe('SettingsCard', () => {
  it('pokazuje tytuł karty, suwaki i pole pytania', async () => {
    await renderCard()

    expect(screen.getByText('Ustawienia')).toBeInTheDocument()
    expect(screen.getByTestId('retrieval-threshold')).toBeInTheDocument()
    expect(screen.getByTestId('retrieval-vector-weight')).toBeInTheDocument()
    expect(screen.getByTestId('retrieval-top-n')).toBeInTheDocument()
    expect(screen.getByTestId('retrieval-question')).toBeInTheDocument()
    expect(screen.getByText('Próg podobieństwa: 0.2')).toBeInTheDocument()
  })

  it('blokuje Uruchom, gdy pytanie jest puste', async () => {
    await renderCard({ question: '' })

    expect(screen.getByTestId('retrieval-run')).toBeDisabled()
  })

  it('blokuje Uruchom, gdy pytanie to same białe znaki', async () => {
    await renderCard({ question: '  ' })

    expect(screen.getByTestId('retrieval-run')).toBeDisabled()
  })

  it('woła onRun po kliknięciu Uruchom, gdy pytanie niepuste', async () => {
    const user = userEvent.setup()
    const { onRun } = await renderCard({ question: 'smok' })

    await user.click(screen.getByTestId('retrieval-run'))

    expect(onRun).toHaveBeenCalledTimes(1)
  })

  it('w trakcie wyszukiwania blokuje Uruchom i niesie napis o trwaniu', async () => {
    await renderCard({ question: 'smok', running: true })

    const button = screen.getByTestId('retrieval-run')
    expect(button).toBeDisabled()
    expect(button).toHaveTextContent('Trwa wyszukiwanie…')
  })

  it('uruchamia test skrótem Ctrl+Enter w polu pytania', async () => {
    const user = userEvent.setup()
    const { onRun } = await renderCard({ question: 'smok' })

    await user.click(screen.getByTestId('retrieval-question'))
    await user.keyboard('{Control>}{Enter}{/Control}')

    expect(onRun).toHaveBeenCalledTimes(1)
  })

  it('nie uruchamia testu skrótem, gdy pytanie jest puste', async () => {
    const user = userEvent.setup()
    const { onRun } = await renderCard({ question: '  ' })

    await user.click(screen.getByTestId('retrieval-question'))
    await user.keyboard('{Control>}{Enter}{/Control}')

    expect(onRun).not.toHaveBeenCalled()
  })

  it('przekazuje nowe ustawienia po zmianie progu strzałką', async () => {
    const user = userEvent.setup()
    const { onSettingsChange } = await renderCard({
      settings: { ...DEFAULT_SETTINGS, similarityThreshold: 0.2 },
    })

    const slider = screen.getByRole('slider', { name: 'Próg podobieństwa' })
    slider.focus()
    await user.keyboard('{ArrowRight}')

    expect(onSettingsChange).toHaveBeenCalledWith({
      ...DEFAULT_SETTINGS,
      similarityThreshold: 0.21,
    })
  })

  it('przekazuje nowe ustawienia po zmianie Top N strzałką', async () => {
    const user = userEvent.setup()
    const { onSettingsChange } = await renderCard()

    const slider = screen.getByRole('slider', { name: 'Liczba wyników (Top N)' })
    slider.focus()
    await user.keyboard('{ArrowRight}')

    expect(onSettingsChange).toHaveBeenCalledWith({ ...DEFAULT_SETTINGS, topN: 11 })
  })

  it('po odsłonięciu sekcji Zaawansowane pozwala wybrać model rerank', async () => {
    const user = userEvent.setup()
    const { onSettingsChange } = await renderCard({ rerankOptions: ['rerank-a', 'rerank-b'] })

    await user.click(screen.getByText('Zaawansowane'))
    const combo = screen.getByRole('combobox', { name: 'Model rerank' })
    await user.click(combo)
    await user.click(await screen.findByRole('option', { name: 'rerank-b' }))

    expect(onSettingsChange).toHaveBeenCalledWith({ ...DEFAULT_SETTINGS, rerankId: 'rerank-b' })
  })

  it('po odsłonięciu sekcji Zaawansowane pozwala wybrać języki międzyjęzykowe (K4)', async () => {
    const user = userEvent.setup()
    const { onSettingsChange } = await renderCard()

    await user.click(screen.getByText('Zaawansowane'))
    const combo = screen.getByRole('combobox', { name: 'Wyszukiwanie międzyjęzykowe' })
    await user.click(combo)
    await user.click(await screen.findByRole('option', { name: 'Niemiecki' }))

    expect(onSettingsChange).toHaveBeenCalledWith({
      ...DEFAULT_SETTINGS,
      crossLanguages: ['German'],
    })
  })

  it('pole pytania ma dostępną nazwę z etykiety', async () => {
    await renderCard()

    expect(screen.getByRole('textbox', { name: 'Pytanie' })).toBeInTheDocument()
  })

  it('pusta etykieta pytania jest zwinięta — nie zasłania placeholdera (D1 E3-7)', async () => {
    await renderCard({ question: '' })

    // Bez `shrink` MUI trzyma etykietę w polu i nakłada ją na placeholder („Wpisz pytanie…”).
    const input = screen.getByTestId('retrieval-question')
    const label = input.closest('.MuiFormControl-root')?.querySelector('label')
    expect(label).toHaveAttribute('data-shrink', 'true')
  })

  it('przy niepustym pytaniu etykieta jest zwinięta', async () => {
    await renderCard({ question: 'smok' })

    // `data-shrink` ustawia `InputLabel` pola; wartość w polu wymusza zwinięcie etykiety nad tekstem.
    const input = screen.getByTestId('retrieval-question')
    const label = input.closest('.MuiFormControl-root')?.querySelector('label')
    expect(label).toHaveAttribute('data-shrink', 'true')
  })
})

describe('SettingsCard — filtr metadanych (SC-E6-1b-06)', () => {
  const expandFilter = async (): Promise<void> => {
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Zaawansowane' }))
    await user.click(await screen.findByText('Filtr metadanych'))
    await screen.findByRole('radiogroup', { name: 'Tryb filtra metadanych' })
  }

  it('sekcja rozwijana: tylko Wyłączony/Ręczny aktywne, auto i półautomatyczne nieaktywne', async () => {
    useSummary(FIXTURE_SUMMARY)
    await renderCard()
    await expandFilter()

    expect(screen.getByRole('radio', { name: 'Wyłączony' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Ręczny' })).toBeEnabled()
    expect(screen.getByRole('radio', { name: 'Automatyczny' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'Półautomatyczny' })).toBeDisabled()
  })

  it('przejście w Ręczny dodaje pusty warunek i idzie przez onSettingsChange', async () => {
    useSummary(FIXTURE_SUMMARY)
    const { onSettingsChange } = await renderCard()
    await expandFilter()

    await userEvent.setup().click(screen.getByRole('radio', { name: 'Ręczny' }))
    expect(onSettingsChange).toHaveBeenLastCalledWith({
      ...DEFAULT_SETTINGS,
      metaDataFilter: {
        ...DEFAULT_SETTINGS.metaDataFilter,
        method: 'manual',
        manual: [{ key: 'rok', op: '=', value: '' }],
      },
    })
  })
})
