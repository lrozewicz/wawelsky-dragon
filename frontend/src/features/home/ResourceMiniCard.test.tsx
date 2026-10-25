import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { Language } from '../../i18n'
import { renderWithProviders } from '../../test/renderWithProviders'

import { ResourceMiniCard } from './ResourceMiniCard'

afterEach(cleanup)

/** Napisy z `locales/{pl,en}/home.json` (odmiana wg reguł liczby mnogiej i18next). */
async function renderSubtitle(filesCount: number, language: Language): Promise<void> {
  await renderWithProviders(
    <ResourceMiniCard title="Baza" href="/dataset/files/ds-1" filesCount={filesCount} />,
    { language },
  )
}

describe('ResourceMiniCard', () => {
  it.each([
    [1, '1 plik'],
    [2, '2 pliki'],
    [5, '5 plików'],
    [22, '22 pliki'],
  ])('pl: filesCount %i → „%s”', async (count, expected) => {
    await renderSubtitle(count, 'pl')

    expect(screen.getByText(expected)).toBeInTheDocument()
  })

  it.each([
    [1, '1 file'],
    [2, '2 files'],
  ])('en: filesCount %i → „%s”', async (count, expected) => {
    await renderSubtitle(count, 'en')

    expect(screen.getByText(expected)).toBeInTheDocument()
  })

  it('opis ma pierwszeństwo przed licznikiem plików', async () => {
    await renderWithProviders(
      <ResourceMiniCard
        title="Baza"
        href="/dataset/files/ds-1"
        description="Opis"
        filesCount={5}
      />,
    )

    expect(screen.getByText('Opis')).toBeInTheDocument()
    expect(screen.queryByText('5 plików')).not.toBeInTheDocument()
  })
})
