import { describe, expect, it } from 'vitest'

import { chunksLinkProps } from './links'

describe('chunksLinkProps', () => {
  it('buduje link do strony chunków z identyfikatorem datasetu i dokumentu', () => {
    expect(chunksLinkProps('ds-1', 'doc-9')).toEqual({
      to: '/chunk/parsed/chunks',
      search: { id: 'ds-1', doc_id: 'doc-9' },
    })
  })
})
