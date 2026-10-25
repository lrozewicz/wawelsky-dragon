/**
 * Błędy walidacji paczki a język UI (SC-V12-06 k.4, K20 §5 p. 2; defekt D1 z QA V12-2-1):
 * w EN Alert dostaje przyczynę po `code` z locale, a polski komunikat serwera (z nazwą wpisu
 * dla `unexpected_entry`) tylko w zwiniętym bloku „Technical details”; PL bez zmian.
 * Rozdzielone z `ImportDialog.test.tsx` przez limit 300 linii (DEC-098).
 */

import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetKbTransfer, setImportPackage } from '../../test/msw/handlers'
import { renderWithProviders } from '../../test/renderWithProviders'

import { ImportDialog } from './ImportDialog'

beforeEach(resetKbTransfer)

afterEach(cleanup)

/** Paczka 1-porcjowa (wzór: `smallPackage` w `ImportDialog.test.tsx`). */
function smallPackage(): File {
  return new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00, 0x00])], 'paczka.wdkb.zip', {
    type: 'application/zip',
  })
}

const MANIFEST_ERROR = {
  code: 'manifest_invalid',
  message: 'Niepoprawny manifest — pole embedding.included: Field required',
}

describe('ImportDialog — błędy walidacji a język UI (SC-V12-06 k.4)', () => {
  it('EN: przyczyna po `code` z locale, komunikat serwera w zwiniętym bloku szczegółów', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<ImportDialog onClose={vi.fn()} onStarted={vi.fn()} />, {
      language: 'en',
    })
    setImportPackage([MANIFEST_ERROR])

    await user.upload(screen.getByTestId('kb-import-input'), [smallPackage()])
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The package has an invalid manifest.',
    )

    const details = screen.getByTestId('kb-import-error-details')
    expect(details, 'szczegół serwera domyślnie zwinięty').not.toHaveAttribute('open')
    expect(details).toHaveTextContent(MANIFEST_ERROR.message)

    await user.click(within(details).getByText('Technical details'))
    expect(details, 'kliknięcie rozwija szczegół serwera').toHaveAttribute('open')
  })

  it('EN: unexpected_entry — tytuł z locale, nazwa wpisu w bloku szczegółów', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<ImportDialog onClose={vi.fn()} onStarted={vi.fn()} />, {
      language: 'en',
    })
    setImportPackage([
      { code: 'unexpected_entry', message: 'Nieoczekiwany wpis „notatka.txt” w paczce' },
    ])

    await user.upload(screen.getByTestId('kb-import-input'), [smallPackage()])
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The package contains a file that is not listed in the manifest.',
    )
    expect(screen.getByTestId('kb-import-error-details')).toHaveTextContent(
      'Nieoczekiwany wpis „notatka.txt” w paczce',
    )
  })

  it('PL: bez zmian — komunikat API jako tekst Alertu, bez bloku szczegółów', async () => {
    const user = userEvent.setup()
    await renderWithProviders(<ImportDialog onClose={vi.fn()} onStarted={vi.fn()} />)
    setImportPackage([MANIFEST_ERROR])

    await user.upload(screen.getByTestId('kb-import-input'), [smallPackage()])
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Niepoprawny manifest — pole embedding.included: Field required',
    )
    expect(screen.queryByTestId('kb-import-error-details')).not.toBeInTheDocument()
  })
})
