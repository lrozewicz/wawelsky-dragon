import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { FeedbackDialog } from './FeedbackDialog'

afterEach(cleanup)

/** Napisy z `locales/pl/*.json` — test chodzi na interfejsie polskim. */
const LABEL = 'Uzasadnienie'
const SEND = 'Wyślij'
const CANCEL = 'Anuluj'

async function renderDialog() {
  const onSubmit = vi.fn()
  const onClose = vi.fn()
  await renderWithProviders(<FeedbackDialog onSubmit={onSubmit} onClose={onClose} />)
  return { onSubmit, onClose }
}

describe('FeedbackDialog', () => {
  it('wysyła wpisane uzasadnienie po trim', async () => {
    const { onSubmit } = await renderDialog()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(LABEL), '  Za krótka odpowiedź  ')
    await user.click(screen.getByRole('button', { name: SEND }))

    expect(onSubmit).toHaveBeenCalledWith('Za krótka odpowiedź')
  })

  it('puste pole wysyła null', async () => {
    const { onSubmit } = await renderDialog()

    await userEvent.setup().click(screen.getByRole('button', { name: SEND }))

    expect(onSubmit).toHaveBeenCalledWith(null)
  })

  it('Anuluj zamyka okno bez wysyłania', async () => {
    const { onSubmit, onClose } = await renderDialog()

    await userEvent.setup().click(screen.getByRole('button', { name: CANCEL }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
