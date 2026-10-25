import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/renderWithProviders'

import { RecentSection } from './RecentSection'

afterEach(cleanup)

type Item = { id: string; name: string }

const baseProps = {
  testId: 'section',
  title: 'Sekcja',
  onRetry: () => {},
  empty: <span>Pusto</span>,
  renderItem: (item: Item) => <a href={`/x/${item.id}`}>{item.name}</a>,
}

describe('RecentSection', () => {
  it('w trakcie ładowania pokazuje szkielety zamiast stanu pustego', async () => {
    await renderWithProviders(
      <RecentSection<Item> {...baseProps} items={undefined} isPending isError={false} />,
    )

    expect(screen.getByTestId('recent-loading')).toBeInTheDocument()
    expect(screen.queryByText('Pusto')).not.toBeInTheDocument()
  })

  it('przy błędzie pokazuje Alert, a „Ponów” wywołuje onRetry', async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    await renderWithProviders(
      <RecentSection<Item>
        {...baseProps}
        items={undefined}
        isPending={false}
        isError
        onRetry={onRetry}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('Nie udało się wczytać danych')
    await user.click(screen.getByRole('button', { name: 'Ponów' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('przy pustej liście pokazuje stan pusty', async () => {
    await renderWithProviders(
      <RecentSection<Item> {...baseProps} items={[]} isPending={false} isError={false} />,
    )

    expect(screen.getByText('Pusto')).toBeInTheDocument()
    expect(screen.queryByTestId('recent-loading')).not.toBeInTheDocument()
  })

  it('renderuje elementy oraz kartę „Zobacz wszystkie”', async () => {
    await renderWithProviders(
      <RecentSection<Item>
        {...baseProps}
        items={[
          { id: 'a', name: 'A' },
          { id: 'b', name: 'B' },
        ]}
        isPending={false}
        isError={false}
        seeAll={<a href="/all">Zobacz wszystkie</a>}
      />,
    )

    expect(screen.getByRole('link', { name: 'A' })).toHaveAttribute('href', '/x/a')
    expect(screen.getByRole('link', { name: 'B' })).toHaveAttribute('href', '/x/b')
    expect(screen.getByRole('link', { name: 'Zobacz wszystkie' })).toHaveAttribute('href', '/all')
  })

  it('renderuje dodatkową kontrolkę z nagłówka', async () => {
    await renderWithProviders(
      <RecentSection<Item>
        {...baseProps}
        items={[]}
        isPending={false}
        isError={false}
        action={<button type="button">Akcja</button>}
      />,
    )

    expect(screen.getByRole('button', { name: 'Akcja' })).toBeInTheDocument()
  })
})
