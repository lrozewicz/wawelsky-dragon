import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { RelatedChips } from './RelatedChips'

afterEach(cleanup)

// Napis z `locales/pl/searches.json` — test chodzi na interfejsie polskim (domyślnym).
const TITLE = 'Pytania pokrewne'

describe('RelatedChips', () => {
  it('pusta lista nie renderuje nic', async () => {
    const { container } = await renderWithProviders(<RelatedChips items={[]} onPick={() => {}} />)

    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument()
  })

  it('renderuje tytuł i chip na każdą pozycję', async () => {
    await renderWithProviders(<RelatedChips items={['a', 'b']} onPick={() => {}} />)

    expect(screen.getByText(TITLE)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'a' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'b' })).toBeInTheDocument()
  })

  it('klik w chip woła onPick z pytaniem', async () => {
    const onPick = vi.fn()
    await renderWithProviders(<RelatedChips items={['a']} onPick={onPick} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'a' }))

    expect(onPick).toHaveBeenCalledWith('a')
  })
})
