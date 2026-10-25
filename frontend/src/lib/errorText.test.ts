import i18next from 'i18next'
import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { ApiError } from '../api/envelope'

import { errorText } from './errorText'

// Tłumaczenie komunikatów serwera testuje `serverMessages.test.ts` (T3a); tu kontrakt
// helpera: ApiError → tłumaczenie wg INVENTORY, inne błędy → bez zmian.
const plMessages: Record<string, string> = {
  'serverMsg.chunkMethodUnsupported':
    'Metoda chunkowania {{chunkMethod}} nie jest obsługiwana przez Wawelsky Dragon',
}

async function createT(): Promise<TFunction> {
  const instance = i18next.createInstance()
  await instance.init({
    lng: 'pl',
    fallbackLng: 'pl',
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
    resources: { pl: { translation: plMessages } },
  })
  return instance.t
}

let t: TFunction

beforeAll(async () => {
  t = await createT()
})

describe('errorText', () => {
  it('ApiError z koperty tłumaczy wg tabeli INVENTORY', () => {
    const error = new ApiError(101, '`chunk_method` foo is not supported by Wawelsky Dragon', 200)
    expect(errorText(error, t)).toBe(
      'Metoda chunkowania foo nie jest obsługiwana przez Wawelsky Dragon',
    )
  })

  it('ApiError bez dopasowania zostawia tekst serwera dosłownie (nie „Nieznany błąd”)', () => {
    const error = new ApiError(102, 'coś nieznanego', 200)
    expect(errorText(error, t)).toBe('coś nieznanego')
  })

  it('zwykły Error — komunikat bez zmian (błędy transportu/sieci)', () => {
    expect(errorText(new Error('Błąd sieci'), t)).toBe('Błąd sieci')
  })

  it('wartość niebędąca błędem — String(value)', () => {
    expect(errorText('sieć padła', t)).toBe('sieć padła')
  })
})
