/**
 * Zaznaczenie wierszy zakładki Pliki (kontrakt WP E3-H2a §K6): po mutacji i po odświeżeniu listy
 * zostają tylko id obecne na aktualnej liście — bez czyszczenia całości. Wiersz, który zniknął
 * z listy, wypada z zaznaczenia i nie wraca jako zaznaczony, gdy pojawi się ponownie.
 */

import { act, cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, documentsHandlers, fixtureDocument } from '../../../test/msw/handlers'
import { server } from '../../../test/msw/server'
import { renderWithProviders } from '../../../test/renderWithProviders'

import { DatasetFilesTab } from './DatasetFilesTab'
import { documentKeys } from './queries'

afterEach(cleanup)

const CHUNKS_ROUTE = '/chunk/parsed/chunks'

const DOC_A = fixtureDocument({ id: 'doc-1', name: 'umowa.pdf', suffix: 'pdf' })
const DOC_B = fixtureDocument({ id: 'doc-2', name: 'raport.docx', suffix: 'docx' })

/** Checkbox wiersza o podanej nazwie pliku (nagłówkowy „Zaznacz wszystkie” nas nie interesuje). */
function rowCheckbox(name: string): HTMLElement {
  const row = screen.getByText(name).closest('[role="row"]')
  if (row === null) throw new Error(`Nie znaleziono wiersza ${name}`)
  return within(row as HTMLElement).getByRole('checkbox')
}

/** Zaznacza wiersze i czeka, aż pasek zbiorczy pokaże ich liczbę. */
async function selectRows(
  user: ReturnType<typeof userEvent.setup>,
  names: string[],
): Promise<void> {
  for (const name of names) {
    await user.click(rowCheckbox(name))
  }
  expect(await screen.findByTestId('bulk-bar')).toHaveTextContent(
    `Zaznaczono: ${String(names.length)}`,
  )
}

describe('DatasetFilesTab — zaznaczenie po odświeżeniu listy', () => {
  it('wypada id wiersza usuniętego z listy i nie wraca, gdy wiersz wróci', async () => {
    let docs = [DOC_A, DOC_B]
    server.use(...documentsHandlers([DOC_A, DOC_B]))
    // Własny handler listy (zarejestrowany później = sprawdzany pierwszy) steruje jej zawartością.
    server.use(
      http.get(apiUrl('/api/v1/datasets/ds-1/documents'), () =>
        HttpResponse.json({ code: 0, message: 'success', data: { docs, total: docs.length } }),
      ),
    )

    const user = userEvent.setup({ delay: null })
    const { queryClient } = await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, {
      routes: [CHUNKS_ROUTE],
    })
    await screen.findByText('umowa.pdf')

    await selectRows(user, ['umowa.pdf', 'raport.docx'])

    // Wiersz `raport.docx` znika z listy (np. usunięty gdzie indziej) i lista się odświeża.
    docs = [DOC_A]
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: documentKeys.all('ds-1') })
    })
    await waitFor(() => {
      expect(screen.queryByText('raport.docx')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('Zaznaczono: 1')

    // Wiersz wraca — nie może wrócić jako zaznaczony: jego id wypadło z zaznaczenia.
    docs = [DOC_A, DOC_B]
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: documentKeys.all('ds-1') })
    })
    await screen.findByText('raport.docx')

    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('Zaznaczono: 1')
    expect(rowCheckbox('umowa.pdf')).toBeChecked()
    expect(rowCheckbox('raport.docx')).not.toBeChecked()
  })

  it('po usunięciu zaznaczonego wiersza zostaje zaznaczenie pozostałych', async () => {
    const bodies: unknown[] = []
    server.use(
      ...documentsHandlers([DOC_A, DOC_B], {
        onRequest: (kind, body) => {
          if (kind === 'delete') bodies.push(body)
        },
      }),
    )

    const user = userEvent.setup({ delay: null })
    await renderWithProviders(<DatasetFilesTab datasetId="ds-1" />, { routes: [CHUNKS_ROUTE] })
    await screen.findByText('umowa.pdf')

    await selectRows(user, ['umowa.pdf', 'raport.docx'])

    // Akcja wiersza usuwa tylko `raport.docx`; `umowa.pdf` zostaje na liście i w zaznaczeniu.
    await user.click(screen.getByTestId('row-delete-doc-2'))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Usuń' }))

    await waitFor(() => expect(bodies).toEqual([{ ids: ['doc-2'] }]))
    await waitFor(() => expect(screen.queryByText('raport.docx')).not.toBeInTheDocument())
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('Zaznaczono: 1')
    // Okno potwierdzenia trzyma resztę drzewa pod `aria-hidden` do końca animacji — czekamy na jego zniknięcie.
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(rowCheckbox('umowa.pdf')).toBeChecked())
  })
})
