/**
 * Hook podsumowania wyszukiwarki (kontrakt WP E4-4b §3): strumień SSE
 * `POST /api/v1/searches/{search_id}/completions` (`parseAs: 'stream'`, jak `useChatStream`),
 * ramki składane reduktorem z E3-5a (`features/chat-stream/reducer`). Nowe pytanie przerywa
 * poprzedni strumień; odmontowanie hooka też.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../../../api/client'
import { readSse } from '../../../lib/sse'
import { initialStreamState, reduce } from '../../chat-stream/reducer'
import type { StreamState } from '../../chat-stream/reducer'
import type { StreamPhase } from '../../chats/stream/useChatStream'

export type UseSearchSummary = {
  phase: StreamPhase
  state: StreamState
  start: (question: string) => Promise<void>
  stop: () => void
  reset: () => void
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'error'
}

export function useSearchSummary(searchId: string): UseSearchSummary {
  const [phase, setPhase] = useState<StreamPhase>('idle')
  const [state, setState] = useState<StreamState>(initialStreamState)

  const controllerRef = useRef<AbortController | null>(null)

  const start = useCallback(
    async (question: string): Promise<void> => {
      // Nowe pytanie przerywa trwający strumień (kontrakt §3) i startuje od czystego stanu.
      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller
      setPhase('streaming')
      setState(initialStreamState)

      let current = initialStreamState

      try {
        const { response } = await api.POST('/api/v1/searches/{search_id}/completions', {
          params: { path: { search_id: searchId } },
          body: { question },
          parseAs: 'stream',
          signal: controller.signal,
        })

        if (!response.ok) {
          if (controller.signal.aborted) return
          setState({ ...current, status: 'error', error: `HTTP ${response.status}` })
          setPhase('error')
          return
        }

        for await (const frame of readSse(response, controller.signal)) {
          current = reduce(current, frame)
          setState(current)
        }

        // `stop()`/`reset()`/nowe `start()` ustawiły już fazę — nie nadpisujemy jej.
        if (controller.signal.aborted) return
        if (current.status === 'error') {
          setPhase('error')
          return
        }

        setPhase('done')
      } catch (error) {
        if (controller.signal.aborted) return
        setState({ ...current, status: 'error', error: errorText(error) })
        setPhase('error')
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null
      }
    },
    [searchId],
  )

  const stop = useCallback(() => {
    const controller = controllerRef.current
    if (controller === null) return
    controller.abort()
    setPhase('aborted')
  }, [])

  const reset = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
    setPhase('idle')
    setState(initialStreamState)
  }, [])

  useEffect(
    () => () => {
      controllerRef.current?.abort()
    },
    [],
  )

  return { phase, state, start, stop, reset }
}
