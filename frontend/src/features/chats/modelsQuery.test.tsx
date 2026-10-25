import { describe, expect, it } from 'vitest'
import { HttpResponse, http } from 'msw'

import { apiUrl, fixtureModel, modelsHandlers } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { renderWithProviders } from '../../test/renderWithProviders'

import { modelsListQueryOptions } from './modelsQuery'

describe('modelsListQueryOptions', () => {
  it('rozpakowuje kopertę i zwraca listę modeli', async () => {
    const model = fixtureModel({ model_id: 'id-chat', name: 'fake-chat' })
    server.use(...modelsHandlers([model]))
    const { queryClient } = await renderWithProviders(<span />)

    await expect(queryClient.fetchQuery(modelsListQueryOptions())).resolves.toEqual([model])
  })

  it('błąd koperty (code ≠ 0) odrzuca zapytanie', async () => {
    server.use(
      http.get(apiUrl('/api/v1/models'), () =>
        HttpResponse.json({ code: 102, message: 'brak modeli', data: null }),
      ),
    )
    const { queryClient } = await renderWithProviders(<span />)

    await expect(queryClient.fetchQuery(modelsListQueryOptions())).rejects.toThrow('brak modeli')
  })
})
