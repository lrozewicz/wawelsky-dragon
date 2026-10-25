import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'
import type { DocAgg } from '../../datasets/retrieval/queries'

import { FileFilter } from './FileFilter'

afterEach(cleanup)

/** Etykiety z `locales/pl/searches.json` — test chodzi na interfejsie polskim. */
const BUTTON = 'Filtruj pliki'
const TITLE = 'Pliki'
const CLEAR = 'Wyczyść filtr'

type FileFilterProps = Parameters<typeof FileFilter>[0]

const AGGS: DocAgg[] = [{ doc_id: 'd1', doc_name: 'a.txt', count: 2 }]

async function renderFilter(overrides: Partial<FileFilterProps> = {}) {
  const onChange = vi.fn()
  const props: FileFilterProps = {
    aggs: AGGS,
    selected: [],
    onChange,
    ...overrides,
  }

  const view = await renderWithProviders(<FileFilter {...props} />)

  return { ...view, onChange }
}

describe('FileFilter', () => {
  it('przycisk bez liczby wybranych, gdy nic nie zaznaczono', async () => {
    await renderFilter()

    expect(screen.getByRole('button', { name: BUTTON })).toBeInTheDocument()
  })

  it('przycisk pokazuje liczbę wybranych plików, gdy większa od zera', async () => {
    await renderFilter({ selected: ['d1'] })

    expect(screen.getByRole('button', { name: 'Filtruj pliki (1)' })).toBeInTheDocument()
  })

  it('po otwarciu pokazuje tytuł i pozycje z aggs', async () => {
    await renderFilter()
    const user = userEvent.setup()

    expect(screen.queryByRole('checkbox')).toBeNull()

    await user.click(screen.getByRole('button', { name: BUTTON }))

    expect(screen.getByText(TITLE)).toBeInTheDocument()
    expect(await screen.findByRole('checkbox', { name: 'a.txt (2)' })).toBeInTheDocument()
  })

  it('zaznaczenie checkboxa zwraca nową listę doc_id', async () => {
    const { onChange } = await renderFilter()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: BUTTON }))
    await user.click(await screen.findByRole('checkbox', { name: 'a.txt (2)' }))

    expect(onChange).toHaveBeenCalledWith(['d1'])
  })

  it('odznaczenie usuwa dokument z listy', async () => {
    const { onChange } = await renderFilter({ selected: ['d1'] })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Filtruj pliki (1)' }))
    await user.click(await screen.findByRole('checkbox', { name: 'a.txt (2)' }))

    expect(onChange).toHaveBeenCalledWith([])
  })

  it('„Wyczyść filtr” zwraca pustą listę wybranych plików', async () => {
    const { onChange } = await renderFilter({ selected: ['d1'] })
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Filtruj pliki (1)' }))
    await user.click(await screen.findByRole('button', { name: CLEAR }))

    expect(onChange).toHaveBeenCalledWith([])
  })
})
