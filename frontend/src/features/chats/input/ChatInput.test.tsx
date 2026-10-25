import { cleanup, fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../../test/renderWithProviders'

import { ChatInput } from './ChatInput'

afterEach(cleanup)

/** Napisy z `locales/pl/*.json` — test chodzi na interfejsie polskim (domyślnym w `renderWithProviders`). */
const PLACEHOLDER = 'Wpisz pytanie…'
const SEND_LABEL = 'Wyślij'
const STOP_LABEL = 'Zatrzymaj'

type ChatInputOverrides = Partial<Parameters<typeof ChatInput>[0]>

async function renderInput(overrides: ChatInputOverrides = {}) {
  const onSend = vi.fn()
  const onStop = vi.fn()
  await renderWithProviders(
    <ChatInput streaming={false} onSend={onSend} onStop={onStop} {...overrides} />,
  )
  return { onSend, onStop, field: screen.getByPlaceholderText(PLACEHOLDER) }
}

describe('ChatInput', () => {
  it('Enter wysyła wpisany tekst i czyści pole', async () => {
    const { onSend, field } = await renderInput()
    const user = userEvent.setup()

    await user.type(field, 'Hej{Enter}')

    expect(onSend).toHaveBeenCalledWith('Hej')
    expect(field).toHaveValue('')
  })

  it('przycisk Wyślij wysyła tekst po trim i czyści pole', async () => {
    const { onSend, field } = await renderInput()
    const user = userEvent.setup()

    await user.type(field, '  Hej  ')
    await user.click(screen.getByRole('button', { name: SEND_LABEL }))

    expect(onSend).toHaveBeenCalledWith('Hej')
    expect(field).toHaveValue('')
  })

  it('Shift+Enter wstawia nową linię i nie wysyła', async () => {
    const { onSend, field } = await renderInput()
    const user = userEvent.setup()

    await user.type(field, 'a{Shift>}{Enter}{/Shift}b')

    expect(field).toHaveValue('a\nb')
    expect(onSend).not.toHaveBeenCalled()
  })

  it('nie wysyła tekstu złożonego z samych spacji', async () => {
    const { onSend, field } = await renderInput()
    const user = userEvent.setup()

    await user.type(field, '   ')

    expect(screen.getByRole('button', { name: SEND_LABEL })).toBeDisabled()

    await user.type(field, '{Enter}')

    expect(onSend).not.toHaveBeenCalled()
    expect(field).toHaveValue('   ')
  })

  it('puste pole nie wysyła po Enter', async () => {
    const { onSend, field } = await renderInput()
    const user = userEvent.setup()

    await user.type(field, '{Enter}')

    expect(onSend).not.toHaveBeenCalled()
  })

  it('Enter podczas kompozycji IME nie wysyła', async () => {
    const { onSend, field } = await renderInput()
    const user = userEvent.setup()

    await user.type(field, 'Hej')
    fireEvent.keyDown(field, { key: 'Enter', isComposing: true })

    expect(onSend).not.toHaveBeenCalled()
    expect(field).toHaveValue('Hej')
  })

  it('w trakcie streamu pokazuje Stop zamiast Wyślij, a Enter nie wysyła', async () => {
    const { onSend, onStop, field } = await renderInput({ streaming: true })
    const user = userEvent.setup()

    expect(screen.queryByRole('button', { name: SEND_LABEL })).not.toBeInTheDocument()
    const stop = screen.getByRole('button', { name: STOP_LABEL })

    await user.type(field, 'Hej{Enter}')
    expect(onSend).not.toHaveBeenCalled()

    await user.click(stop)
    expect(onStop).toHaveBeenCalledTimes(1)
    expect(field).toHaveValue('Hej')
  })

  it('pole i przycisk są nieaktywne, gdy disabled', async () => {
    const { onSend, field } = await renderInput({ disabled: true })

    expect(field).toBeDisabled()
    expect(screen.getByRole('button', { name: SEND_LABEL })).toBeDisabled()

    fireEvent.keyDown(field, { key: 'Enter' })

    expect(onSend).not.toHaveBeenCalled()
  })

  it('chip warunku filtra jest przyciskiem i wywołuje onEditFilter (SC-E67-06 k5)', async () => {
    const onEditFilter = vi.fn()
    await renderInput({ filterLabels: ['typ = raport'], onEditFilter })

    await userEvent.setup().click(screen.getByRole('button', { name: 'typ = raport' }))

    expect(onEditFilter).toHaveBeenCalledTimes(1)
  })
})
