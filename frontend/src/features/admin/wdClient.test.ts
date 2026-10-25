import { describe, expect, it } from 'vitest'

import { WD_ERROR_SLUGS, WdApiError, wdCall, wdErrorKey } from './wdClient'

/** Wynik openapi-fetch: ciało w `data`/`error`, status w `response`. */
function result(status: number, body: { data?: unknown; error?: unknown; statusText?: string }) {
  const response = new Response(null, { status, statusText: body.statusText })
  return Promise.resolve({ data: body.data, error: body.error, response })
}

describe('wdCall', () => {
  it('rozpakowuje sukces {data} do samego data', async () => {
    await expect(wdCall(result(200, { data: { data: { a: 1 } } }))).resolves.toEqual({ a: 1 })
  })

  it('zwraca undefined dla 204 bez ciała', async () => {
    await expect(wdCall(result(204, {}))).resolves.toBeUndefined()
  })

  it('rzuca WdApiError z kodem i statusem przy 409', async () => {
    const promise = wdCall(result(409, { error: { error: { code: 'conflict', message: 'x' } } }))

    await expect(promise).rejects.toBeInstanceOf(WdApiError)
    await expect(promise).rejects.toMatchObject({
      code: 'conflict',
      message: 'x',
      httpStatus: 409,
    })
  })

  it('przy 500 z pustym/nie-JSON ciałem daje kod unknown i statusText', async () => {
    await expect(
      wdCall(result(500, { statusText: 'Internal Server Error' })),
    ).rejects.toMatchObject({
      code: 'unknown',
      message: 'Internal Server Error',
      httpStatus: 500,
    })
  })

  it('przy błędzie bez poprawnego kodu sluga daje unknown', async () => {
    await expect(
      wdCall(result(400, { error: { error: { code: 42, message: 'zły typ' } } })),
    ).rejects.toMatchObject({ code: 'unknown', message: 'zły typ', httpStatus: 400 })
  })

  it('przenosi obiekt `details` z ciała błędu (K3 §3 p. 4)', async () => {
    await expect(
      wdCall(
        result(409, {
          error: {
            error: { code: 'export_in_progress', message: 'trwa', details: { task_id: 't1' } },
          },
        }),
      ),
    ).rejects.toMatchObject({ code: 'export_in_progress', details: { task_id: 't1' } })
  })

  it('pomija `details`, gdy nie jest obiektem', async () => {
    await expect(
      wdCall(result(409, { error: { error: { code: 'conflict', message: 'x', details: 't1' } } })),
    ).rejects.toMatchObject({ details: undefined })
  })
})

describe('wdErrorKey', () => {
  it('znany slug mapuje na admin.error.<slug>', () => {
    expect(wdErrorKey(new WdApiError('conflict', '', 409))).toBe('admin.error.conflict')
  })

  it('nieznany slug mapuje na admin.error.unknown', () => {
    expect(wdErrorKey(new WdApiError('coś_nowego', '', 400))).toBe('admin.error.unknown')
  })

  it('błąd spoza WdApiError mapuje na admin.error.unknown', () => {
    expect(wdErrorKey(new Error())).toBe('admin.error.unknown')
    expect(wdErrorKey('nie-błąd')).toBe('admin.error.unknown')
  })
})

describe('WD_ERROR_SLUGS', () => {
  it('zawiera dziesięć slugów z kontraktu', () => {
    expect(WD_ERROR_SLUGS).toHaveLength(10)
    expect([...WD_ERROR_SLUGS]).toEqual([
      'validation_failed',
      'not_found',
      'conflict',
      'permission_denied',
      'unauthorized',
      'authentication_failed',
      'operation_not_allowed',
      'upstream_error',
      'busy',
      'rate_limited',
    ])
  })
})
