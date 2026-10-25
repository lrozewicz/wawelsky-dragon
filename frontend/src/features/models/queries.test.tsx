import { cleanup, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'

import { apiUrl, fixtureModels } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { hasDefaultModels, useShowModelsAlert } from './queries'
import type { DefaultModels } from './queries'

afterEach(cleanup)

function AlertProbe() {
  return <span>{String(useShowModelsAlert())}</span>
}

function modelsHandler(models: DefaultModels) {
  return http.get(apiUrl('/api/v1/users/me/models'), () =>
    HttpResponse.json({ code: 0, message: 'success', data: models }),
  )
}

describe('hasDefaultModels', () => {
  it('wymaga niepustego LLM i embeddingu', () => {
    expect(hasDefaultModels(fixtureModels)).toBe(true)
    expect(hasDefaultModels({ ...fixtureModels, llm_id: '' })).toBe(false)
    expect(hasDefaultModels({ ...fixtureModels, embd_id: '' })).toBe(false)
  })
})

describe('useShowModelsAlert', () => {
  it('bez alertu, gdy oba domyślne modele są ustawione', async () => {
    const { queryClient } = await renderWithProviders(<AlertProbe />)

    await waitFor(() => {
      expect(queryClient.getQueryState(['models', 'me'])?.status).toBe('success')
    })
    expect(screen.getByText('false')).toBeInTheDocument()
  })

  it('pokazuje alert, gdy brak domyślnego LLM', async () => {
    server.use(modelsHandler({ ...fixtureModels, llm_id: '' }))

    await renderWithProviders(<AlertProbe />)

    expect(await screen.findByText('true')).toBeInTheDocument()
  })

  it('pokazuje alert, gdy brak domyślnego embeddingu', async () => {
    server.use(modelsHandler({ ...fixtureModels, embd_id: '' }))

    await renderWithProviders(<AlertProbe />)

    expect(await screen.findByText('true')).toBeInTheDocument()
  })

  it('bez alertu, gdy żądanie się nie powiedzie', async () => {
    server.use(
      http.get(apiUrl('/api/v1/users/me/models'), () =>
        HttpResponse.json({ code: 500, message: 'boom' }, { status: 500 }),
      ),
    )

    const { queryClient } = await renderWithProviders(<AlertProbe />)

    await waitFor(() => {
      expect(queryClient.getQueryState(['models', 'me'])?.status).toBe('error')
    })
    expect(screen.getByText('false')).toBeInTheDocument()
  })
})
