import * as React from 'react'
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import { afterEach, describe, expect, it } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import type { DialogProps } from './useDialogs'
import { useDialogs } from './useDialogs'

afterEach(cleanup)

function CustomDialog({ open, payload, onClose }: DialogProps<{ title: string }, string>) {
  return (
    <Dialog open={open} onClose={() => onClose('anulowano')}>
      <DialogTitle>{payload.title}</DialogTitle>
      <DialogContent>treść własnego okna</DialogContent>
      <DialogActions>
        <Button onClick={() => onClose('wynik')}>Zatwierdź własne</Button>
      </DialogActions>
    </Dialog>
  )
}

function DialogTester() {
  const dialogs = useDialogs()
  const [log, setLog] = React.useState<string[]>([])
  const customPromise = React.useRef<Promise<string> | null>(null)

  const append = (entry: string) => setLog((entries) => [...entries, entry])

  return (
    <React.Fragment>
      <Button
        onClick={() => {
          void dialogs.alert('msg').then(() => append('alert-zamkniety'))
        }}
      >
        alert
      </Button>
      <Button
        onClick={() => {
          void dialogs.confirm('pytanie').then((value) => append(`confirm:${String(value)}`))
        }}
      >
        confirm
      </Button>
      <Button
        onClick={() => {
          void dialogs.prompt('podaj').then((value) => append(`prompt:${String(value)}`))
        }}
      >
        prompt
      </Button>
      <Button
        onClick={() => {
          const promise = dialogs.open(CustomDialog, { title: 'Custom' })
          customPromise.current = promise
          void promise.then((value) => append(`open:${value}`))
        }}
      >
        open
      </Button>
      <Button
        onClick={() => {
          void dialogs.close(customPromise.current as Promise<string>, 'wynik')
        }}
      >
        close
      </Button>
      <ul>
        {log.map((entry, index) => (
          <li key={index}>{entry}</li>
        ))}
      </ul>
    </React.Fragment>
  )
}

// Zamknięte okno zostaje w DOM do końca animacji — czekamy, aż zniknie, żeby kolejne zapytania były jednoznaczne.
async function expectNoDialog() {
  await waitFor(() => expect(screen.queryAllByRole('dialog')).toHaveLength(0))
}

describe('useDialogs', () => {
  it("alert('msg') pokazuje tekst i przycisk OK, a po kliknięciu rozwiązuje Promise", async () => {
    const user = userEvent.setup()
    await renderWithProviders(<DialogTester />)

    await user.click(screen.getByRole('button', { name: 'alert' }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('msg')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'OK' }))

    await waitFor(() => expect(screen.getByText('alert-zamkniety')).toBeInTheDocument())
  })

  it("confirm('pytanie'): Anuluj → false, potem OK → true", async () => {
    const user = userEvent.setup()
    await renderWithProviders(<DialogTester />)

    await user.click(screen.getByRole('button', { name: 'confirm' }))
    expect(screen.getByText('pytanie')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Anuluj' }))
    await waitFor(() => expect(screen.getByText('confirm:false')).toBeInTheDocument())
    await expectNoDialog()

    await user.click(screen.getByRole('button', { name: 'confirm' }))
    await user.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(screen.getByText('confirm:true')).toBeInTheDocument())
  })

  it("prompt('podaj'): wpisanie abc + OK → 'abc', Anuluj → null", async () => {
    const user = userEvent.setup()
    await renderWithProviders(<DialogTester />)

    await user.click(screen.getByRole('button', { name: 'prompt' }))
    await user.type(screen.getByRole('textbox'), 'abc')
    await user.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(screen.getByText('prompt:abc')).toBeInTheDocument())
    await expectNoDialog()

    await user.click(screen.getByRole('button', { name: 'prompt' }))
    await user.click(screen.getByRole('button', { name: 'Anuluj' }))
    await waitFor(() => expect(screen.getByText('prompt:null')).toBeInTheDocument())
  })

  it('open(CustomDialog, payload) + close(dialog, wynik) zwraca wynik', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<DialogTester />)

    await user.click(screen.getByRole('button', { name: 'open' }))
    expect(screen.getByText('treść własnego okna')).toBeInTheDocument()

    // Otwarte okno modala oznacza resztę drzewa jako aria-hidden, więc rola jest niewidoczna —
    // klikamy po tekście, poza modalem (sam modal nie blokuje zdarzenia).
    fireEvent.click(screen.getByText('close'))
    await waitFor(() => expect(screen.getByText('open:wynik')).toBeInTheDocument())
  })

  it('własne okno może zamknąć się samo przez onClose', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<DialogTester />)

    await user.click(screen.getByRole('button', { name: 'open' }))
    await user.click(screen.getByRole('button', { name: 'Zatwierdź własne' }))
    await waitFor(() => expect(screen.getByText('open:wynik')).toBeInTheDocument())
  })
})
