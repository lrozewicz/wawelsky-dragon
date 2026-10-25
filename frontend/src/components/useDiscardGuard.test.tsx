/**
 * Testy wspólnego strażnika niezapisanych zmian (SC-V12-07): czysty formularz zamyka szufladę
 * od razu, brudny pyta dialogiem z nazwą kontekstu; „Wróć do edycji” (domyślny fokus, Esc)
 * zostawia stan, „Odrzuć” woła `onClose`; zamknięcie szuflady (`open=false`) gasi otwarte
 * pytanie — ponowne otwarcie startuje czysto (U7).
 */

import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'

import { renderWithProviders } from '../test/renderWithProviders'

import { useDiscardGuard } from './useDiscardGuard'
import type { DiscardContext } from './DiscardChangesDialog'

const TITLE = 'Odrzucić zmiany?'
const KEEP = 'Wróć do edycji'
const DISCARD = 'Odrzuć'
const CLOSE = 'Zamknij szufladę'

/** Wspólna forma użycia w szufladzie: `requestClose` pod przyciskiem, `dialog` obok. */
function Harness(props: {
  dirty: boolean
  open?: boolean
  context?: DiscardContext
  onClose: () => void
}) {
  const { requestClose, dialog } = useDiscardGuard({
    dirty: props.dirty,
    onClose: props.onClose,
    context: props.context ?? 'chat',
    open: props.open ?? true,
  })
  return (
    <>
      <button onClick={requestClose}>{CLOSE}</button>
      {dialog}
    </>
  )
}

/** Wariant szuflady: podniesiony „brudny” przełącza się przyciskiem (jak z formularza). */
function DirtyHarness(props: { onClose: () => void }) {
  const [dirty, setDirty] = useState(false)
  const { requestClose, dialog } = useDiscardGuard({
    dirty,
    onClose: props.onClose,
    context: 'chat',
    open: true,
  })
  return (
    <>
      <button onClick={() => setDirty(true)}>Zmień</button>
      <button onClick={requestClose}>{CLOSE}</button>
      {dialog}
    </>
  )
}

afterEach(cleanup)

describe('useDiscardGuard', () => {
  it('czysty formularz: requestClose zamyka od razu, bez dialogu', async () => {
    const onClose = vi.fn()
    await renderWithProviders(<Harness dirty={false} onClose={onClose} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: CLOSE }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument()
  })

  it('brudny formularz: requestClose pokazuje dialog z kontekstem; „Wróć do edycji” zostawia stan', async () => {
    const onClose = vi.fn()
    await renderWithProviders(<Harness dirty onClose={onClose} context="metadata" />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: CLOSE }))

    expect(await screen.findByText(TITLE)).toBeInTheDocument()
    expect(
      screen.getByText('Niezapisane zmiany w metadanych pliku zostaną utracone.'),
    ).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: KEEP }))
    await waitFor(() => expect(screen.queryByText(TITLE)).not.toBeInTheDocument())
    expect(onClose).not.toHaveBeenCalled()
  })

  it('„Odrzuć” woła onClose raz i chowa dialog', async () => {
    const onClose = vi.fn()
    await renderWithProviders(<Harness dirty onClose={onClose} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: CLOSE }))
    await screen.findByText(TITLE)
    await user.click(screen.getByRole('button', { name: DISCARD }))

    expect(onClose).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.queryByText(TITLE)).not.toBeInTheDocument())
  })

  it('Esc w dialogu = „Wróć do edycji”, która ma domyślny fokus', async () => {
    const onClose = vi.fn()
    await renderWithProviders(<Harness dirty onClose={onClose} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: CLOSE }))
    await screen.findByText(TITLE)
    await waitFor(() => expect(screen.getByRole('button', { name: KEEP })).toHaveFocus())

    await user.keyboard('{Escape}')

    await waitFor(() => expect(screen.queryByText(TITLE)).not.toBeInTheDocument())
    expect(onClose).not.toHaveBeenCalled()
  })

  it('dopiero zmiana na brudną włącza pytanie (dirty steruje ścieżką zamknięcia)', async () => {
    const onClose = vi.fn()
    await renderWithProviders(<DirtyHarness onClose={onClose} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: CLOSE }))
    expect(onClose).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Zmień' }))
    await user.click(screen.getByRole('button', { name: CLOSE }))
    expect(await screen.findByText(TITLE)).toBeInTheDocument()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('zamknięcie szuflady (open=false) gasi otwarte pytanie — ponowne otwarcie czyste', async () => {
    const onClose = vi.fn()
    const view = await renderWithProviders(<Harness dirty onClose={onClose} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: CLOSE }))
    await screen.findByText(TITLE)

    view.rerender(<Harness dirty={false} open={false} onClose={onClose} />)
    await waitFor(() => expect(screen.queryByText(TITLE)).not.toBeInTheDocument())

    view.rerender(<Harness dirty={false} open onClose={onClose} />)
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: CLOSE }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
